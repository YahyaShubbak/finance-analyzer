"""Card bills paid from the bank account are transfers, not expenses — the
card's purchases are the expenses. Covers the cases independent testers
found counted twice. All data invented."""
from __future__ import annotations

import io

import pytest

from tests.pdf_fixtures import write_text_pdf


def _account(client, name, account_type):
    r = client.post("/api/accounts", json={"name": name, "account_type": account_type})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _import(client, account_id, name, content: bytes, mime="text/csv"):
    files = {"file": (name, io.BytesIO(content), mime)}
    preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id})
    assert preview.status_code == 200, preview.text
    commit = client.post("/api/imports/commit", json={"staging_id": preview.json()["staging_id"], "account_id": account_id})
    assert commit.status_code == 200, commit.text
    return preview.json()


def _statement(tmp_path, lines):
    path = write_text_pdf(tmp_path / "statement.pdf", [
        "Credit Card Statement", "VISA ending 1234", "Statement Period: 01.03.2026 - 31.03.2026", *lines,
    ])
    return path.read_bytes()


def _by_amount(client, account_id):
    return {t["amount_minor"]: t for t in client.get("/api/transactions", params={"account_id": account_id}).json()["items"]}


BANK = (b"Date,Description,Amount\n"
        b"2026-03-03,Visa Kreditkartenabrechnung Februar,-80.00\n"
        b"2026-04-06,Visa Kreditkartenabrechnung Maerz,-100.00\n")


def test_the_statements_payment_line_settles_the_previous_bill(client, tmp_path):
    bank = _account(client, "Giro", "checking")
    card = _account(client, "Visa", "credit_card")
    _import(client, bank, "bank.csv", BANK)
    _import(client, card, "march.pdf", _statement(tmp_path, [
        "02.03.2026 Restaurant Beispiel 100.00 EUR",
        "04.03.2026 Payment received thank you -80.00 EUR",
        "Statement Total: 100.00 EUR",
    ]), "application/pdf")

    debits = _by_amount(client, bank)
    assert debits[-10000]["transaction_type"] == "transfer"  # settles the March statement
    assert debits[-8000]["transaction_type"] == "transfer"   # paid the February bill (its payment line is in March)
    assert client.get("/api/analytics/totals").json()["expenses_minor"] == 10000


def test_reconciliation_does_not_depend_on_the_import_order(client, tmp_path):
    """The card's export brings the payment line first and gets paired with
    the bank debit; the statement imported afterwards still claims it."""
    bank = _account(client, "Giro", "checking")
    card = _account(client, "Visa", "credit_card")
    _import(client, card, "export.csv", (
        b"Date,Description,Amount\n"
        b"2026-03-02,Restaurant Beispiel,-100.00\n"
        b"2026-04-06,Payment received thank you,100.00\n"
    ))
    _import(client, bank, "bank.csv", BANK)
    assert _by_amount(client, bank)[-10000]["transaction_type"] == "transfer"  # paired with the export's line

    _import(client, card, "march.pdf", _statement(tmp_path, [
        "02.03.2026 Restaurant Beispiel 100.00 EUR",
        "Statement Total: 100.00 EUR",
    ]), "application/pdf")
    statement = client.get(f"/api/credit-cards/{card}/statements").json()[0]
    detail = client.get(f"/api/reconciliation/statements/{statement['id']}").json()
    assert detail["bank_payment"]["transaction"]["amount_minor"] == -10000
    totals = client.get("/api/analytics/totals").json()
    assert totals["expenses_minor"] == 10000 + 8000  # the purchase, and the February bill (no purchases imported)


def test_card_bills_without_imported_purchases_are_an_expense_of_their_own(client, tmp_path):
    """A card bill whose card has no purchases imported is the only record of
    that spending: an expense, filed as a card bill — not as a transfer."""
    bank = _account(client, "Giro", "checking")
    _import(client, bank, "bank.csv", BANK)
    debit = _by_amount(client, bank)[-10000]
    assert (debit["transaction_type"], debit["category"]) == ("expense", "Card bills")
    categories = {c["category"] for c in client.get("/api/analytics/by-category").json()}
    assert "Card bills" in categories and "Transfers" not in categories


def test_card_bills_filed_as_transfers_by_an_older_version_are_refiled(client):
    from sqlmodel import Session, select

    import app.db.session as db_session
    from app.db.models import Transaction
    from app.services.transfer_marking import settle_flagged_transfers

    bank = _account(client, "Giro", "checking")
    _import(client, bank, "bank.csv", BANK)
    with Session(db_session.engine) as session:
        for tx in session.exec(select(Transaction)).all():
            tx.category = "Transfers"
            session.add(tx)
        session.commit()
        settle_flagged_transfers(session)
        assert {t.category for t in session.exec(select(Transaction)).all()} == {"Card bills"}


EXPORT = (b"Date,Description,Amount\n"
          b"2026-03-02,Restaurant Beispiel,-60.00\n"
          b"2026-03-10,Buchhandlung Beispiel,-25.50\n"
          b"2026-03-20,Erstattung Buchhandlung,5.50\n")
BILL = (b"Date,Description,Amount\n"
        b"2026-04-14,American Express Europe Abrechnung,-80.00\n"
        b"2026-05-14,American Express Europe Abrechnung,-120.00\n")


@pytest.mark.parametrize("order", [("card", "bank"), ("bank", "card")])
def test_an_export_matching_a_later_bill_is_reconciled_like_a_statement(client, order):
    """Only the card's CSV (one billing period) is imported, no statement:
    the bill paying exactly its purchases must not count a second time —
    in either import order."""
    bank = _account(client, "Giro", "checking")
    card = _account(client, "Amex", "credit_card")
    files = {"card": (card, "amex.csv", EXPORT), "bank": (bank, "bank.csv", BILL)}
    for which in order:
        account_id, name, content = files[which]
        _import(client, account_id, name, content)

    debits = _by_amount(client, bank)
    assert (debits[-8000]["transaction_type"], debits[-8000]["category"]) == ("transfer", "Transfers")
    assert debits[-12000]["transaction_type"] == "expense"  # its purchases aren't imported
    statements = client.get(f"/api/credit-cards/{card}/statements").json()
    assert [s["statement_total_minor"] for s in statements] == [8000]
    assert statements[0]["reconciliation_status"] == "reconciled"
    totals = client.get("/api/analytics/totals", params={"account_id": f"{bank},{card}"}).json()
    assert totals["expenses_minor"] == 8000 + 12000


def test_an_export_is_not_taken_for_a_bill_of_another_amount(client):
    bank = _account(client, "Giro", "checking")
    card = _account(client, "Amex", "credit_card")
    _import(client, card, "amex.csv", EXPORT)
    _import(client, bank, "bank.csv", BILL.replace(b"-80.00", b"-81.00"))
    assert client.get(f"/api/credit-cards/{card}/statements").json() == []
