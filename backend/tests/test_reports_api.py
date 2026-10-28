"""Tests for the Reports feature's backend endpoints: account-level
breakdown (credit cards included) and transfers-excluded summary — plus
date-range filtering across all report endpoints, verified against real
imported data flowing through the actual import/reconciliation pipeline
(not hand-constructed rows), so these tests double as accounting-
correctness regression coverage.
"""
from __future__ import annotations

import io

from tests.pdf_fixtures import write_text_pdf


def _create_account(client, name, account_type, currency="EUR"):
    r = client.post("/api/accounts", json={"name": name, "account_type": account_type, "currency": currency})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _import_csv(client, filename, content: bytes, account_id: int):
    files = {"file": (filename, io.BytesIO(content), "text/csv")}
    preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id})
    assert preview.status_code == 200, preview.text
    p = preview.json()
    commit = client.post("/api/imports/commit", json={"staging_id": p["staging_id"], "account_id": account_id})
    assert commit.status_code == 200, commit.text
    return commit.json()


def _import_pdf(client, tmp_path, name, lines, account_id):
    path = write_text_pdf(tmp_path / name, lines)
    with open(path, "rb") as f:
        files = {"file": (name, f, "application/pdf")}
        preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id})
    assert preview.status_code == 200, preview.text
    p = preview.json()
    commit = client.post("/api/imports/commit", json={"staging_id": p["staging_id"], "account_id": account_id})
    assert commit.status_code == 200, commit.text
    return commit.json()


def _get_statement_id(client, cc_account_id):
    r = client.get(f"/api/credit-cards/{cc_account_id}/statements")
    assert r.status_code == 200
    return r.json()[0]["id"]


def _full_scenario(client, tmp_path):
    """Checking account with salary + groceries + a CC bill payment,
    and a credit card with one purchase — reconciled. Returns the
    account ids.

    Note: checking<->savings transfer-PAIR detection (app.normalization.transfers,
    built in an earlier phase) is not currently invoked by the import
    pipeline — only the credit-card statement/bank-payment match (via the
    reconciliation engine) automatically marks a transaction as a
    transfer. This scenario therefore only exercises the CC-payment path,
    which is the one actually wired end-to-end.
    """
    checking_id = _create_account(client, "Checking", "checking")
    cc_id = _create_account(client, "VISA", "credit_card")

    _import_csv(
        client, "checking_march.csv",
        b"Date,Description,Amount\n"
        b"2026-03-01,Salary,2500.00\n"
        b"2026-03-05,REWE Supermarket,-60.00\n"
        b"2026-03-12,Credit Card Payment,-100.00\n",
        checking_id,
    )
    _import_pdf(client, tmp_path, "cc_march.pdf", [
        "Credit Card Statement", "VISA ending 1234",
        "Statement Period: 01.03.2026 - 10.03.2026",
        "02.03.2026 Amazon.de 100.00 EUR",
        "Statement Total: 100.00 EUR",
    ], cc_id)
    stmt_id = _get_statement_id(client, cc_id)
    client.get(f"/api/reconciliation/statements/{stmt_id}")  # triggers reconciliation + transfer marking

    return checking_id, cc_id


# ---------------------------------------------------------------------------

def test_totals_and_category_breakdown_exclude_transfers(client, tmp_path):
    _full_scenario(client, tmp_path)

    totals = client.get("/api/analytics/totals").json()
    # Income: 2500 salary. Expenses: 60 groceries + 100 CC purchase = 160.
    # The CC bill payment (-100) must NOT appear as an additional expense.
    assert totals["income_minor"] == 250000
    assert totals["expenses_minor"] == 16000
    assert totals["net_minor"] == 234000

    categories = {c["category"]: c["amount_minor"] for c in client.get("/api/analytics/by-category").json()}
    assert categories["Groceries"] == 6000
    assert categories["Shopping"] == 10000  # Amazon purchase


def test_account_breakdown(client, tmp_path):
    checking_id, cc_id = _full_scenario(client, tmp_path)

    r = client.get("/api/analytics/by-account")
    assert r.status_code == 200
    by_id = {a["account_id"]: a for a in r.json()}

    checking = by_id[checking_id]
    assert checking["income_minor"] == 250000
    assert checking["expenses_minor"] == 6000  # only groceries — CC payment excluded as a transfer
    assert checking["net_minor"] == 244000

    cc = by_id[cc_id]
    assert cc["expenses_minor"] == 10000
    assert cc["income_minor"] == 0


def test_transfers_summary_shows_excluded_amount(client, tmp_path):
    _full_scenario(client, tmp_path)

    r = client.get("/api/analytics/transfers-summary")
    assert r.status_code == 200
    summary = r.json()
    # The reconciled CC bill payment (-100.00) is marked as a transfer.
    assert summary["total_transferred_minor"] == 10000
    assert summary["transfer_count"] == 1


def test_reports_respect_date_range(client, tmp_path):
    checking_id = _create_account(client, "Checking", "checking")
    _import_csv(
        client, "two_months.csv",
        b"Date,Description,Amount\n"
        b"2026-03-05,REWE Supermarket,-50.00\n"
        b"2026-04-05,Lidl Supermarket,-70.00\n",
        checking_id,
    )

    march_only = client.get("/api/analytics/totals", params={"start": "2026-03-01", "end": "2026-03-31"}).json()
    assert march_only["expenses_minor"] == 5000

    april_only = client.get("/api/analytics/totals", params={"start": "2026-04-01", "end": "2026-04-30"}).json()
    assert april_only["expenses_minor"] == 7000

    both = client.get("/api/analytics/totals", params={"start": "2026-03-01", "end": "2026-04-30"}).json()
    assert both["expenses_minor"] == 12000

    march_categories = client.get(
        "/api/analytics/by-category", params={"start": "2026-03-01", "end": "2026-03-31"}
    ).json()
    assert march_categories == [{"category": "Groceries", "currency": "EUR", "amount_minor": 5000}]

    march_over_time = client.get(
        "/api/analytics/over-time", params={"start": "2026-03-01", "end": "2026-03-31"}
    ).json()
    assert march_over_time == [{"month": "2026-03", "currency": "EUR", "income_minor": 0, "expenses_minor": 5000}]


def test_category_transactions_add_up_to_the_category_bar(client):
    """Clicking a category in Reports lists the transactions behind its bar:
    expenses and refunds of that category, never income, transfers or
    duplicates — and their total is exactly the bar's amount."""
    checking_id = _create_account(client, "Checking", "checking")
    _import_csv(
        client, "march.csv",
        b"Date,Description,Amount\n"
        b"2026-03-01,Salary,2500.00\n"
        b"2026-03-05,REWE Supermarket,-60.00\n"
        b"2026-03-09,REWE Supermarket,-25.50\n"
        b"2026-03-12,Lidl,-14.20\n"
        b"2026-03-20,Netflix,-12.99\n"
        b"2026-04-02,Lidl,-9.00\n",
        checking_id,
    )
    q = {"start": "2026-03-01", "end": "2026-03-31"}
    bars = {(b["category"], b["currency"]): b["amount_minor"] for b in client.get("/api/analytics/by-category", params=q).json()}
    assert bars[("Groceries", "EUR")] == 9970

    r = client.get("/api/analytics/by-category/transactions", params={**q, "category": "Groceries", "currency": "EUR"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amount_minor"] == bars[("Groceries", "EUR")]
    assert body["total"] == 3
    assert [t["amount_minor"] for t in body["items"]] == [-1420, -2550, -6000]  # newest first, April excluded
    assert sum(-t["amount_minor"] for t in body["items"]) == body["amount_minor"]

    # paging keeps the total of all matching transactions
    page = client.get(
        "/api/analytics/by-category/transactions",
        params={**q, "category": "Groceries", "currency": "EUR", "page_size": 2, "page": 2},
    ).json()
    assert [t["amount_minor"] for t in page["items"]] == [-6000]
    assert page["amount_minor"] == 9970 and page["total"] == 3

    # income in a category never shows up as spending
    income = client.get("/api/analytics/by-category/transactions", params={**q, "category": "Salary", "currency": "EUR"}).json()
    assert income["total"] == 0 and income["amount_minor"] == 0


def test_category_transactions_can_be_searched_and_sorted(client):
    checking_id = _create_account(client, "Checking", "checking")
    card_id = _create_account(client, "A-Card", "credit_card")
    _import_csv(
        client, "march.csv",
        b"Date,Description,Amount\n"
        b"2026-03-05,REWE Supermarket,-60.00\n"
        b"2026-03-09,REWE Supermarket,-25.50\n"
        b"2026-03-12,Lidl,-14.20\n",
        checking_id,
    )
    _import_csv(
        client, "card.csv",
        b"Date,Description,Amount\n"
        b"2026-03-07,Lidl,-3.10\n"
        b"2026-03-08,Kiosk Beispiel,-4.00\n"
        b"2026-03-10,Lidl Erstattung,1.50\n"
        b"2026-03-11,Buchladen Muster,-9.90\n",
        card_id,
    )
    base = {"start": "2026-03-01", "end": "2026-03-31", "category": "Groceries", "currency": "EUR"}
    url = "/api/analytics/by-category/transactions"

    found = client.get(url, params={**base, "search": "lidl"}).json()
    assert sorted(t["amount_minor"] for t in found["items"]) == [-1420, -310, 150]
    assert found["total"] == 3 and found["amount_minor"] == 1420 + 310 - 150  # the sum of what was found

    by_amount = client.get(url, params={**base, "sort": "amount", "order": "asc"}).json()["items"]
    amounts = [t["amount_minor"] for t in by_amount]
    assert amounts == sorted(amounts) and amounts[0] == -6000 and amounts[-1] == 150

    by_account = client.get(url, params={**base, "sort": "account", "order": "asc"}).json()["items"]
    assert by_account[0]["account_name"] == "A-Card" and by_account[-1]["account_name"] == "Checking"

    assert client.get(url, params={**base, "sort": "nonsense"}).status_code == 422
