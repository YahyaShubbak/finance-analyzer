"""Tests for Milestone 4, Feature 4: optional per-account opening balance.

Verifies the three balance figures stay genuinely distinct
(transactions_balance_minor / opening_balance_minor / current_balance_minor),
that setting an opening balance never touches accounting/reconciliation
elsewhere, and that it can be cleared explicitly.
"""
from __future__ import annotations

import io


def _create_account(client, name, account_type="checking"):
    r = client.post("/api/accounts", json={"name": name, "account_type": account_type, "currency": "EUR"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _import_csv(client, filename, content: bytes, account_id: int):
    files = {"file": (filename, io.BytesIO(content), "text/csv")}
    preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id})
    assert preview.status_code == 200, preview.text
    p = preview.json()
    commit = client.post("/api/imports/commit", json={"staging_id": p["staging_id"], "account_id": account_id, "row_decisions": []})
    assert commit.status_code == 200, commit.text
    return commit.json()


def _get_account(client, account_id):
    return next(a for a in client.get("/api/accounts").json() if a["id"] == account_id)


# ---------------------------------------------------------------------------

def test_new_account_has_no_opening_balance_by_default(client):
    account_id = _create_account(client, "Checking")
    account = _get_account(client, account_id)
    assert account["opening_balance_minor"] is None
    assert account["opening_balance_date"] is None
    assert account["transactions_balance_minor"] == 0
    assert account["current_balance_minor"] == 0


def test_current_balance_equals_transactions_balance_when_no_opening_balance_set(client):
    """Backward compatibility: an account with no opening balance behaves
    exactly as before this feature — current balance is just the sum of
    imported transactions."""
    account_id = _create_account(client, "Checking")
    _import_csv(client, "a.csv", b"Date,Description,Amount\n2026-01-01,Salary,1000.00\n2026-01-05,Groceries,-40.00\n", account_id)

    account = _get_account(client, account_id)
    assert account["transactions_balance_minor"] == 96000
    assert account["current_balance_minor"] == 96000
    assert account["opening_balance_minor"] is None


def test_set_opening_balance_adds_to_current_balance(client):
    account_id = _create_account(client, "Checking")
    _import_csv(client, "a.csv", b"Date,Description,Amount\n2026-01-05,Groceries,-40.00\n", account_id)

    r = client.patch(f"/api/accounts/{account_id}", json={
        "opening_balance_minor": 500000, "opening_balance_date": "2026-01-01",
    })
    assert r.status_code == 200
    account = r.json()

    # transactions_balance_minor is untouched — still the plain sum of
    # imported transactions, regardless of the opening balance.
    assert account["transactions_balance_minor"] == -4000
    assert account["opening_balance_minor"] == 500000
    assert account["opening_balance_date"] == "2026-01-01"
    # current_balance_minor combines both.
    assert account["current_balance_minor"] == 500000 - 4000


def test_transactions_before_opening_balance_date_excluded_from_current_balance(client):
    """The whole point of an opening-balance date: transactions before it
    are presumed already reflected in the opening figure, so they must
    not be double-counted into the current balance — but they still count
    in transactions_balance_minor (the plain, unfiltered sum)."""
    account_id = _create_account(client, "Checking")
    _import_csv(
        client, "a.csv",
        b"Date,Description,Amount\n"
        b"2025-12-15,Old Purchase Before Tracking,-200.00\n"  # before opening date
        b"2026-01-10,New Purchase After Tracking,-30.00\n",   # after opening date
        account_id,
    )
    client.patch(f"/api/accounts/{account_id}", json={
        "opening_balance_minor": 100000, "opening_balance_date": "2026-01-01",
    })

    account = _get_account(client, account_id)
    # transactions_balance_minor: both transactions counted, unfiltered.
    assert account["transactions_balance_minor"] == -20000 + -3000
    # current_balance_minor: opening balance + only the transaction ON/AFTER the opening date.
    assert account["current_balance_minor"] == 100000 - 3000


def test_transaction_on_opening_date_itself_is_included(client):
    account_id = _create_account(client, "Checking")
    _import_csv(client, "a.csv", b"Date,Description,Amount\n2026-01-01,Same Day,-10.00\n", account_id)
    client.patch(f"/api/accounts/{account_id}", json={
        "opening_balance_minor": 50000, "opening_balance_date": "2026-01-01",
    })

    account = _get_account(client, account_id)
    assert account["current_balance_minor"] == 50000 - 1000  # on-the-date transaction included


def test_opening_balance_can_be_cleared_explicitly(client):
    account_id = _create_account(client, "Checking")
    _import_csv(client, "a.csv", b"Date,Description,Amount\n2026-01-05,Groceries,-40.00\n", account_id)
    client.patch(f"/api/accounts/{account_id}", json={
        "opening_balance_minor": 500000, "opening_balance_date": "2026-01-01",
    })
    assert _get_account(client, account_id)["opening_balance_minor"] == 500000

    r = client.patch(f"/api/accounts/{account_id}", json={
        "opening_balance_minor": None, "opening_balance_date": None,
    })
    assert r.status_code == 200
    account = r.json()
    assert account["opening_balance_minor"] is None
    assert account["opening_balance_date"] is None
    assert account["current_balance_minor"] == account["transactions_balance_minor"]


def test_opening_balance_does_not_affect_income_expense_totals(client):
    """Reports/Dashboard totals must be completely unaffected by an
    opening balance — it's a balance-display concept only."""
    account_id = _create_account(client, "Checking")
    _import_csv(client, "a.csv", b"Date,Description,Amount\n2026-01-05,Salary,1000.00\n2026-01-06,Groceries,-40.00\n", account_id)

    before = client.get("/api/analytics/totals").json()

    client.patch(f"/api/accounts/{account_id}", json={
        "opening_balance_minor": 999999, "opening_balance_date": "2026-01-01",
    })

    after = client.get("/api/analytics/totals").json()
    assert after == before


def test_opening_balance_does_not_affect_reconciliation(client, tmp_path):
    """Setting an opening balance on either the checking or credit-card
    account must not change reconciliation status/amounts at all."""
    from tests.pdf_fixtures import write_text_pdf

    checking_id = _create_account(client, "Checking")
    cc_id = _create_account(client, "VISA", "credit_card")

    path = write_text_pdf(tmp_path / "cc.pdf", [
        "Credit Card Statement", "VISA ending 1234",
        "Statement Period: 01.01.2026 - 10.01.2026",
        "02.01.2026 Amazon.de 50.00 EUR",
        "Statement Total: 50.00 EUR",
    ])
    with open(path, "rb") as f:
        preview = client.post("/api/imports/preview", files={"file": ("cc.pdf", f, "application/pdf")}, data={"account_id": cc_id})
    p = preview.json()
    commit = client.post("/api/imports/commit", json={"staging_id": p["staging_id"], "account_id": cc_id, "row_decisions": []})
    stmt_id = commit.json()["credit_card_statement_id"]

    _import_csv(client, "bank.csv", b"Date,Description,Amount\n2026-01-12,Credit Card Payment,-50.00\n", checking_id)
    before = client.get(f"/api/reconciliation/statements/{stmt_id}").json()
    assert before["status"] == "reconciled"

    client.patch(f"/api/accounts/{checking_id}", json={"opening_balance_minor": 200000, "opening_balance_date": "2026-01-01"})
    client.patch(f"/api/accounts/{cc_id}", json={"opening_balance_minor": -5000, "opening_balance_date": "2026-01-01"})

    after = client.get(f"/api/reconciliation/statements/{stmt_id}").json()
    assert after["status"] == "reconciled"
    assert after["transaction_total_minor"] == before["transaction_total_minor"]
    assert after["statement_total_minor"] == before["statement_total_minor"]


def test_opening_balance_persists_across_restart(tmp_path):
    from sqlmodel import Session, SQLModel, create_engine, select

    from app.db.models import Account, AccountType

    db_path = tmp_path / "finance.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    from datetime import date
    with Session(engine) as s:
        acc = Account(
            name="Checking", account_type=AccountType.CHECKING, currency="EUR",
            opening_balance_minor=250000, opening_balance_date=date(2026, 1, 1),
        )
        s.add(acc)
        s.commit()

    engine2 = create_engine(f"sqlite:///{db_path}")
    with Session(engine2) as s:
        acc = s.exec(select(Account)).one()
        assert acc.opening_balance_minor == 250000
        assert acc.opening_balance_date == date(2026, 1, 1)
