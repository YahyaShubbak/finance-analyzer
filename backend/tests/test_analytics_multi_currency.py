"""Tests for currency-aware aggregation in analytics_service (Phase 1 of
the multi-currency fix): single-currency behavior stays unchanged, mixed
currencies in scope are never blindly summed together.
"""
from __future__ import annotations

import io


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


def test_single_currency_totals_unchanged_shape(client):
    checking_id = _create_account(client, "Checking", "checking")
    _import_csv(
        client, "eur_only.csv",
        b"Date,Description,Amount\n"
        b"2026-03-01,Salary,2500.00\n"
        b"2026-03-05,REWE Supermarket,-60.00\n",
        checking_id,
    )

    totals = client.get("/api/analytics/totals").json()
    assert totals["is_mixed_currency"] is False
    assert totals["currency"] == "EUR"
    assert totals["by_currency"] is None
    assert totals["income_minor"] == 250000
    assert totals["expenses_minor"] == 6000
    assert totals["net_minor"] == 244000

    categories = client.get("/api/analytics/by-category").json()
    assert categories == [{"category": "Groceries", "currency": "EUR", "amount_minor": 6000}]

    monthly = client.get("/api/analytics/over-time").json()
    assert monthly == [{"month": "2026-03", "currency": "EUR", "income_minor": 250000, "expenses_minor": 6000}]


def test_mixed_currency_totals_split_by_currency(client):
    eur_id = _create_account(client, "Checking EUR", "checking", currency="EUR")
    usd_id = _create_account(client, "Checking USD", "checking", currency="USD")

    _import_csv(
        client, "eur.csv",
        b"Date,Description,Amount\n"
        b"2026-03-01,Salary,2000.00\n"
        b"2026-03-05,REWE Supermarket,-50.00\n",
        eur_id,
    )
    _import_csv(
        client, "usd.csv",
        b"Date,Description,Amount\n"
        b"2026-03-02,US Salary,3000.00\n"
        b"2026-03-06,US Supermarket,-80.00\n",
        usd_id,
    )

    totals = client.get("/api/analytics/totals").json()
    assert totals["is_mixed_currency"] is True
    assert totals["currency"] is None
    assert totals["income_minor"] is None
    assert totals["expenses_minor"] is None
    assert totals["net_minor"] is None
    assert totals["transaction_count"] == 4

    by_currency = {row["currency"]: row for row in totals["by_currency"]}
    assert by_currency["EUR"]["income_minor"] == 200000
    assert by_currency["EUR"]["expenses_minor"] == 5000
    assert by_currency["EUR"]["net_minor"] == 195000
    assert by_currency["USD"]["income_minor"] == 300000
    assert by_currency["USD"]["expenses_minor"] == 8000
    assert by_currency["USD"]["net_minor"] == 292000

    categories = client.get("/api/analytics/by-category").json()
    by_pair = {(c["category"], c["currency"]): c["amount_minor"] for c in categories}
    assert by_pair[("Groceries", "EUR")] == 5000
    assert by_pair[("Groceries", "USD")] == 8000

    monthly = client.get("/api/analytics/over-time").json()
    by_month_currency = {(m["month"], m["currency"]): m for m in monthly}
    assert by_month_currency[("2026-03", "EUR")]["income_minor"] == 200000
    assert by_month_currency[("2026-03", "USD")]["income_minor"] == 300000

    transfers = client.get("/api/analytics/transfers-summary").json()
    assert transfers["transfer_count"] == 0
    assert transfers["is_mixed_currency"] is False  # no transfers at all -> 0 currencies, treated as single/empty


def test_by_account_breakdown_carries_account_currency(client):
    eur_id = _create_account(client, "Checking EUR", "checking", currency="EUR")
    usd_id = _create_account(client, "Checking USD", "checking", currency="USD")
    _import_csv(client, "eur.csv", b"Date,Description,Amount\n2026-03-01,Salary,2000.00\n", eur_id)
    _import_csv(client, "usd.csv", b"Date,Description,Amount\n2026-03-02,US Salary,3000.00\n", usd_id)

    by_account = client.get("/api/analytics/by-account").json()
    by_id = {row["account_id"]: row for row in by_account}
    assert by_id[eur_id]["currency"] == "EUR"
    assert by_id[usd_id]["currency"] == "USD"


def test_archived_account_excluded_from_mixed_currency_detection(client):
    eur_id = _create_account(client, "Checking EUR", "checking", currency="EUR")
    usd_id = _create_account(client, "Checking USD", "checking", currency="USD")
    _import_csv(client, "eur.csv", b"Date,Description,Amount\n2026-03-01,Salary,2000.00\n", eur_id)
    _import_csv(client, "usd.csv", b"Date,Description,Amount\n2026-03-02,US Salary,3000.00\n", usd_id)

    r = client.patch(f"/api/accounts/{usd_id}", json={"is_archived": True})
    assert r.status_code == 200, r.text

    totals = client.get("/api/analytics/totals").json()
    assert totals["is_mixed_currency"] is False
    assert totals["currency"] == "EUR"
    assert totals["income_minor"] == 200000


def test_per_transaction_currency_override_within_one_account(client):
    """A single account can hold transactions in more than one currency
    when the source file carries an explicit currency column (e.g. a
    foreign-currency credit-card line item) — confirms totals split by
    Transaction.currency, not Account.currency, even in that case."""
    checking_id = _create_account(client, "Checking", "checking", currency="EUR")
    _import_csv(
        client, "mixed_within_account.csv",
        b"Date,Description,Amount,Currency\n"
        b"2026-03-01,EUR Purchase,-40.00,EUR\n"
        b"2026-03-02,Foreign Purchase,-25.00,USD\n",
        checking_id,
    )

    totals = client.get("/api/analytics/totals").json()
    assert totals["is_mixed_currency"] is True
    by_currency = {row["currency"]: row for row in totals["by_currency"]}
    assert by_currency["EUR"]["expenses_minor"] == 4000
    assert by_currency["USD"]["expenses_minor"] == 2500

    # by-account breakdown still reports the account's nominal currency
    # (EUR) for this one row — a documented limitation, not a bug.
    by_account = client.get("/api/analytics/by-account").json()
    assert by_account[0]["currency"] == "EUR"
