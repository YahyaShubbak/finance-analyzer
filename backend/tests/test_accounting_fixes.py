"""Regression tests for totals that used to come out wrong: credit-card
reconciliation side effects, transfer pairs, refunds, categories and the
migration bridge."""
from __future__ import annotations

import io

from sqlalchemy import create_engine, inspect
from sqlmodel import select

from app.db.models import CategoryRule
from app.normalization.category import DEFAULT_CATEGORY_RULES, categorize, sync_default_category_rules
from tests.pdf_fixtures import write_text_pdf


def _create_account(client, name, account_type="checking"):
    r = client.post("/api/accounts", json={"name": name, "account_type": account_type})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _import_csv(client, content: bytes, account_id: int, name="a.csv"):
    p = client.post("/api/imports/preview", files={"file": (name, io.BytesIO(content), "text/csv")},
                    data={"account_id": account_id}).json()
    r = client.post("/api/imports/commit", json={"staging_id": p["staging_id"], "account_id": account_id})
    assert r.status_code == 200, r.text
    return r.json()


def _import_cc_pdf(client, tmp_path, account_id, lines, name="cc.pdf"):
    path = write_text_pdf(tmp_path / name, lines)
    with open(path, "rb") as f:
        p = client.post("/api/imports/preview", files={"file": (name, f, "application/pdf")},
                        data={"account_id": account_id}).json()
    r = client.post("/api/imports/commit", json={"staging_id": p["staging_id"], "account_id": account_id})
    assert r.status_code == 200, r.text
    return r.json()


def _tx(client, description):
    items = client.get("/api/transactions", params={"page_size": 500}).json()["items"]
    return next(t for t in items if t["normalized_description"] == description)


_CC_50 = [
    "Credit Card Statement", "Statement Period: 01.03.2026 - 10.03.2026",
    "02.03.2026 Amazon.de 50.00 EUR", "Statement Total: 50.00 EUR",
]


def test_viewing_pages_never_changes_totals(client, tmp_path):
    """A non-exact debit near the statement date used to be claimed as the
    card payment — merely by opening the Credit Cards page."""
    checking = _create_account(client, "Checking")
    card = _create_account(client, "VISA", "credit_card")
    _import_cc_pdf(client, tmp_path, card, _CC_50)
    _import_csv(client, b"Date,Description,Amount\n2026-03-12,REWE,-48.00\n", checking)

    before = client.get("/api/analytics/totals").json()
    statement_id = client.get(f"/api/credit-cards/{card}/statements").json()[0]["id"]
    client.get("/api/credit-cards")
    detail = client.get(f"/api/reconciliation/statements/{statement_id}").json()
    after = client.get("/api/analytics/totals").json()

    assert before == after
    assert _tx(client, "REWE")["is_transfer"] is False
    # ... and a purchase is not even suggested: only a debit of exactly the
    # amount, or one that looks like a card payment, is.
    assert detail["bank_payment"]["status"] == "not_found"
    assert detail["bank_payment"]["recommended_transaction_id"] is None


def test_exact_payment_linked_automatically_and_unlinking_restores_it(client, tmp_path):
    checking = _create_account(client, "Checking")
    card = _create_account(client, "VISA", "credit_card")
    _import_cc_pdf(client, tmp_path, card, _CC_50)
    _import_csv(client, b"Date,Description,Amount\n2026-03-12,Kreditkarte,-50.00\n", checking)
    statement_id = client.get(f"/api/credit-cards/{card}/statements").json()[0]["id"]

    assert _tx(client, "Kreditkarte")["is_transfer"] is True
    assert client.get("/api/analytics/totals").json()["expenses_minor"] == 5000  # counted once

    r = client.post(f"/api/reconciliation/statements/{statement_id}/clear-bank-payment")
    assert r.json()["bank_payment"]["status"] == "suggested"
    assert _tx(client, "Kreditkarte")["is_transfer"] is False
    assert _tx(client, "Kreditkarte")["transaction_type"] == "expense"


def test_choosing_another_payment_releases_the_previous_one(client, tmp_path):
    checking = _create_account(client, "Checking")
    card = _create_account(client, "VISA", "credit_card")
    _import_cc_pdf(client, tmp_path, card, _CC_50)
    _import_csv(client, b"Date,Description,Amount\n2026-03-12,Wrong,-50.00\n2026-03-20,Right,-50.00\n", checking)
    statement_id = client.get(f"/api/credit-cards/{card}/statements").json()[0]["id"]

    client.post(f"/api/reconciliation/statements/{statement_id}/select-bank-payment",
                json={"transaction_id": _tx(client, "Wrong")["id"]})
    client.post(f"/api/reconciliation/statements/{statement_id}/select-bank-payment",
                json={"transaction_id": _tx(client, "Right")["id"]})

    assert _tx(client, "Right")["is_transfer"] is True
    assert _tx(client, "Wrong")["is_transfer"] is False


def test_removing_the_card_statement_releases_its_bank_payment(client, tmp_path):
    checking = _create_account(client, "Checking")
    card = _create_account(client, "VISA", "credit_card")
    cc_import = _import_cc_pdf(client, tmp_path, card, _CC_50)
    _import_csv(client, b"Date,Description,Amount\n2026-03-12,Kreditkarte,-50.00\n", checking)
    assert _tx(client, "Kreditkarte")["is_transfer"] is True

    assert client.delete(f"/api/imports/{cc_import['import_id']}").status_code == 200
    assert _tx(client, "Kreditkarte")["is_transfer"] is False
    assert client.get("/api/analytics/totals").json()["expenses_minor"] == 5000


def test_manual_type_change_on_settlement_puts_statement_back_to_pending(client, tmp_path):
    checking = _create_account(client, "Checking")
    card = _create_account(client, "VISA", "credit_card")
    _import_cc_pdf(client, tmp_path, card, _CC_50)
    _import_csv(client, b"Date,Description,Amount\n2026-03-12,Kreditkarte,-50.00\n", checking)
    statement_id = client.get(f"/api/credit-cards/{card}/statements").json()[0]["id"]

    client.patch(f"/api/transactions/{_tx(client, 'Kreditkarte')['id']}", json={"transaction_type": "expense"})
    detail = client.get(f"/api/reconciliation/statements/{statement_id}").json()
    assert detail["status"] == "pending"
    # ... and the user's correction is not overridden by a later re-check.
    client.post(f"/api/reconciliation/statements/{statement_id}/find-payment")
    assert _tx(client, "Kreditkarte")["is_transfer"] is False


def test_manual_type_change_reverts_the_transfer_partner(client):
    checking = _create_account(client, "Checking")
    savings = _create_account(client, "Savings", "savings")
    _import_csv(client, b"Date,Description,Amount\n2026-03-15,Out,-500.00\n", checking)
    _import_csv(client, b"Date,Description,Amount\n2026-03-16,In,500.00\n", savings, name="b.csv")
    assert _tx(client, "In")["is_transfer"] is True

    client.patch(f"/api/transactions/{_tx(client, 'Out')['id']}", json={"transaction_type": "expense"})
    assert _tx(client, "In")["is_transfer"] is False
    assert _tx(client, "In")["transaction_type"] == "income"


def test_card_payment_line_and_refund_are_not_income(client, tmp_path):
    card = _create_account(client, "VISA", "credit_card")
    _import_cc_pdf(client, tmp_path, card, [
        "Credit Card Statement", "Statement Period: 01.03.2026 - 31.03.2026",
        "02.03.2026 Amazon.de 200.00 EUR",
        "05.03.2026 Payment received - thank you -400.00 EUR",
        "08.03.2026 Amazon.de Refund -50.00 EUR",
        "Statement Total: 150.00 EUR",
    ])
    totals = client.get("/api/analytics/totals").json()
    assert totals["income_minor"] == 0          # neither the payment nor the refund is income
    assert totals["expenses_minor"] == 15000    # the refund reduces spending
    assert _tx(client, "Payment received - thank you")["is_transfer"] is True


def test_transfer_between_currencies_not_paired(client):
    checking = _create_account(client, "Checking")
    r = client.post("/api/accounts", json={"name": "USD", "account_type": "savings", "currency": "USD"})
    _import_csv(client, b"Date,Description,Amount\n2026-03-15,Rent,-900.00\n", checking)
    _import_csv(client, b"Date,Description,Amount\n2026-03-15,Client payment,900.00\n", r.json()["id"], name="b.csv")
    assert _tx(client, "Rent")["is_transfer"] is False


def test_invalid_account_ids_return_422(client):
    assert client.get("/api/analytics/totals", params={"account_id": "abc"}).status_code == 422


def test_budget_category_with_slash(client):
    r = client.put("/api/budgets/Haus%2FGarten", json={"amount_minor": 10000, "currency": "EUR"})
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "Haus/Garten"


def test_account_iban_and_currency_validated(client):
    ok = client.post("/api/accounts", json={"name": "A", "account_type": "checking",
                                             "iban": "de02 1203 0000 0000 2020 51"})
    assert ok.json()["iban"] == "DE02120300000000202051"
    assert client.post("/api/accounts", json={"name": "B", "account_type": "checking",
                                               "iban": "DE02120300000000202052"}).status_code == 422
    assert client.post("/api/accounts", json={"name": "C", "account_type": "checking",
                                               "currency": "€"}).status_code == 422


# --- categories ---------------------------------------------------------------

def _rules():
    return [CategoryRule(id=i, pattern=p, is_regex=True, match_field="any", category=c, amount_sign=s, priority=pr)
            for i, (p, c, s, pr) in enumerate(DEFAULT_CATEGORY_RULES)]


def test_default_category_rules_use_word_boundaries():
    rules = _rules()
    assert categorize("Deutsche Rentenversicherung", None, -10000, rules) == "Insurance"
    assert categorize("Espresso House", None, -450, rules) != "Transport"
    assert categorize("Brewery Tap", None, -1200, rules) != "Groceries"
    assert categorize("Miete Oktober", None, -90000, rules) == "Housing"
    assert categorize("Netflix", None, -1299, rules) == "Subscriptions"


def test_sign_specific_rules():
    rules = _rules()
    assert categorize("Finanzamt", "Lohnsteuer", -50000, rules) == "Taxes"
    assert categorize("Arbeitgeber AG", "Gehalt September", 250000, rules) == "Salary"
    assert categorize("Arbeitgeber AG", "Gehalt Rückforderung", -10000, rules) != "Salary"


def test_builtin_rules_are_replaced_on_upgrade(session):
    session.add(CategoryRule(pattern="rent|miete", is_regex=True, match_field="merchant", category="Housing"))
    session.commit()
    sync_default_category_rules(session)
    patterns = {r.pattern for r in session.exec(select(CategoryRule)).all()}
    assert "rent|miete" not in patterns
    assert patterns == {p for p, *_ in DEFAULT_CATEGORY_RULES}


def test_reapply_rules_respects_manual_corrections(client):
    account = _create_account(client, "Checking")
    _import_csv(client, b"Date,Description,Amount\n2026-03-01,Kino Palast,-12.00\n2026-03-02,Kino Palast,-9.00\n", account)
    items = client.get("/api/transactions").json()["items"]
    client.patch(f"/api/transactions/{items[0]['id']}", json={"category": "Dates"})
    client.post(f"/api/transactions/{items[1]['id']}/category-rule", json={"category": "Cinema"})

    r = client.post("/api/transactions/reapply-rules")
    assert r.status_code == 200
    by_id = {t["id"]: t for t in client.get("/api/transactions").json()["items"]}
    assert by_id[items[0]["id"]]["category"] == "Dates"     # manual correction kept
    assert by_id[items[1]["id"]]["category"] == "Cinema"


# --- migration bridge -----------------------------------------------------------

def test_unversioned_old_database_gets_missing_migrations(tmp_path):
    """A database created by create_all before Alembic existed, from an
    OLD models.py, must receive the migrations it is missing — stamping it
    as "head" used to skip them."""
    from alembic import command

    from app.db.migrate import _alembic_config, upgrade_database

    db = tmp_path / "old.db"
    url = f"sqlite:///{db}"
    command.upgrade(_alembic_config(url), "0f1597c97f2c")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE alembic_version")
    engine.dispose()

    upgrade_database(db)

    engine = create_engine(url)
    inspector = inspect(engine)
    assert "budgets" in inspector.get_table_names()
    assert "opening_balance_minor" in {c["name"] for c in inspector.get_columns("accounts")}
    engine.dispose()
