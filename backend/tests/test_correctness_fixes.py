"""Regression tests for Milestone 4 Feature 1: archived-account exclusion
from aggregate totals, and SQL-level (not in-memory) pagination.
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


# ---------------------------------------------------------------------------
# Archived-account exclusion
# ---------------------------------------------------------------------------

def test_archived_account_excluded_from_totals(client):
    active_id = _create_account(client, "Active Checking")
    closed_id = _create_account(client, "Old Checking")

    _import_csv(client, "a.csv", b"Date,Description,Amount\n2026-01-01,Salary,1000.00\n", active_id)
    _import_csv(client, "b.csv", b"Date,Description,Amount\n2026-01-01,Old Salary,500.00\n", closed_id)

    before = client.get("/api/analytics/totals").json()
    assert before["income_minor"] == 150000  # both accounts still active

    client.patch(f"/api/accounts/{closed_id}", json={"is_archived": True})

    after = client.get("/api/analytics/totals").json()
    assert after["income_minor"] == 100000  # only the active account now


def test_archived_account_excluded_from_category_breakdown_and_account_breakdown(client):
    active_id = _create_account(client, "Active Checking")
    closed_id = _create_account(client, "Old Checking")

    _import_csv(client, "a.csv", b"Date,Description,Amount\n2026-01-01,REWE Supermarket,-40.00\n", active_id)
    _import_csv(client, "b.csv", b"Date,Description,Amount\n2026-01-01,REWE Supermarket,-25.00\n", closed_id)
    client.patch(f"/api/accounts/{closed_id}", json={"is_archived": True})

    categories = client.get("/api/analytics/by-category").json()
    groceries = next(c for c in categories if c["category"] == "Groceries")
    assert groceries["amount_minor"] == 4000  # only the active account's spending

    breakdown = client.get("/api/analytics/by-account").json()
    assert closed_id not in [a["account_id"] for a in breakdown]


def test_archived_account_excluded_from_transfers_summary(client):
    checking_id = _create_account(client, "Checking")
    old_savings_id = _create_account(client, "Old Savings", "savings")

    _import_csv(client, "a.csv", b"Date,Description,Amount\n2026-01-01,Transfer Out,-100.00\n", checking_id)
    _import_csv(client, "b.csv", b"Date,Description,Amount\n2026-01-02,Transfer In,100.00\n", old_savings_id)

    before = client.get("/api/analytics/transfers-summary").json()
    assert before["transfer_count"] == 1  # one movement, both legs in scope -> counted once
    assert before["total_transferred_minor"] == 10000

    client.patch(f"/api/accounts/{old_savings_id}", json={"is_archived": True})

    after = client.get("/api/analytics/transfers-summary").json()
    assert after["transfer_count"] == 1  # only the still-active checking leg
    assert after["total_transferred_minor"] == 10000


def test_explicit_account_id_filter_still_includes_archived_account(client):
    """Explicitly asking for a specific account's own data (e.g. viewing
    its own transaction history) is a deliberate choice and should not be
    silently blocked just because the account is archived."""
    closed_id = _create_account(client, "Old Checking")
    _import_csv(client, "a.csv", b"Date,Description,Amount\n2026-01-01,Salary,500.00\n", closed_id)
    client.patch(f"/api/accounts/{closed_id}", json={"is_archived": True})

    totals = client.get("/api/analytics/totals", params={"account_id": str(closed_id)}).json()
    assert totals["income_minor"] == 50000


# ---------------------------------------------------------------------------
# SQL-level pagination
# ---------------------------------------------------------------------------

def test_pagination_returns_correct_total_and_pages(client):
    account_id = _create_account(client, "Checking")
    rows = "\n".join(f"2026-01-{i:02d},Item {i},-{i}.00" for i in range(1, 26))
    _import_csv(client, "many.csv", f"Date,Description,Amount\n{rows}\n".encode(), account_id)

    page1 = client.get("/api/transactions", params={"page": 1, "page_size": 10}).json()
    assert page1["total"] == 25
    assert len(page1["items"]) == 10

    page3 = client.get("/api/transactions", params={"page": 3, "page_size": 10}).json()
    assert len(page3["items"]) == 5  # remainder

    # No overlap between pages.
    page1_ids = {t["id"] for t in page1["items"]}
    page2 = client.get("/api/transactions", params={"page": 2, "page_size": 10}).json()
    page2_ids = {t["id"] for t in page2["items"]}
    assert page1_ids.isdisjoint(page2_ids)


def test_pagination_stable_ordering_across_pages(client):
    """Every transaction must appear exactly once across all pages, with
    no duplicates or gaps — proves the SQL ORDER BY + OFFSET/LIMIT is
    deterministic."""
    account_id = _create_account(client, "Checking")
    rows = "\n".join(f"2026-02-{(i % 28) + 1:02d},Item {i},-{i}.00" for i in range(1, 41))
    _import_csv(client, "many.csv", f"Date,Description,Amount\n{rows}\n".encode(), account_id)

    seen_ids = set()
    page = 1
    while True:
        body = client.get("/api/transactions", params={"page": page, "page_size": 7}).json()
        if not body["items"]:
            break
        for t in body["items"]:
            assert t["id"] not in seen_ids
            seen_ids.add(t["id"])
        page += 1

    assert len(seen_ids) == 40
