"""Tests for the Budget feature: CRUD (upsert-by-category), and
budget-vs-actual status computed over real imported/categorized data."""
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


def test_budgets_empty_initially(client):
    r = client.get("/api/budgets")
    assert r.status_code == 200
    assert r.json() == []


def test_upsert_is_create_then_update_not_duplicate(client):
    r1 = client.put("/api/budgets/Groceries", json={"amount_minor": 40000, "currency": "EUR"})
    assert r1.status_code == 200, r1.text
    budget_id = r1.json()["id"]
    assert r1.json()["amount_minor"] == 40000

    r2 = client.put("/api/budgets/Groceries", json={"amount_minor": 50000, "currency": "EUR"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["id"] == budget_id
    assert r2.json()["amount_minor"] == 50000

    all_budgets = client.get("/api/budgets").json()
    assert len(all_budgets) == 1


def test_delete_budget(client):
    r = client.put("/api/budgets/Groceries", json={"amount_minor": 40000})
    budget_id = r.json()["id"]

    d = client.delete(f"/api/budgets/{budget_id}")
    assert d.status_code == 204

    assert client.get("/api/budgets").json() == []


def test_delete_nonexistent_budget_returns_404(client):
    r = client.delete("/api/budgets/9999")
    assert r.status_code == 404


def test_budget_status_computes_actual_from_real_import(client):
    checking_id = _create_account(client, "Checking", "checking")
    _import_csv(
        client, "march.csv",
        b"Date,Description,Amount\n"
        b"2026-03-01,Salary,2500.00\n"
        b"2026-03-05,REWE Supermarket,-60.00\n"
        b"2026-03-12,Lidl Supermarket,-25.00\n"
        b"2026-04-01,Aldi Supermarket,-30.00\n",  # different month — must not count
        checking_id,
    )
    client.put("/api/budgets/Groceries", json={"amount_minor": 10000, "currency": "EUR"})

    status = client.get("/api/budgets/status", params={"month": "2026-03"}).json()
    assert status["month"] == "2026-03"
    assert len(status["items"]) == 1
    item = status["items"][0]
    assert item["category"] == "Groceries"
    assert item["budget_minor"] == 10000
    assert item["actual_minor"] == 8500
    assert item["remaining_minor"] == 1500
    assert item["over_budget"] is False
    assert item["percent_used"] == 85.0


def test_budget_status_over_budget(client):
    checking_id = _create_account(client, "Checking", "checking")
    _import_csv(
        client, "march.csv",
        b"Date,Description,Amount\n"
        b"2026-03-05,REWE Supermarket,-150.00\n",
        checking_id,
    )
    client.put("/api/budgets/Groceries", json={"amount_minor": 10000, "currency": "EUR"})

    status = client.get("/api/budgets/status", params={"month": "2026-03"}).json()
    item = status["items"][0]
    assert item["actual_minor"] == 15000
    assert item["remaining_minor"] == -5000
    assert item["over_budget"] is True


def test_budget_status_excludes_duplicates_and_transfers(client):
    checking_id = _create_account(client, "Checking", "checking")
    _create_account(client, "VISA", "credit_card")

    # Two identical rows -> the second is flagged as an exact duplicate
    # and must not count toward actual spend.
    _import_csv(
        client, "march1.csv",
        b"Date,Description,Amount\n"
        b"2026-03-05,REWE Supermarket,-50.00\n",
        checking_id,
    )
    _import_csv(
        client, "march1_again.csv",
        b"Date,Description,Amount\n"
        b"2026-03-05,REWE Supermarket,-50.00\n"
        b"2026-03-20,Unrelated Row To Change File Checksum,-1.00\n",
        checking_id,
    )

    client.put("/api/budgets/Groceries", json={"amount_minor": 100000, "currency": "EUR"})
    status = client.get("/api/budgets/status", params={"month": "2026-03"}).json()
    item = status["items"][0]
    assert item["actual_minor"] == 5000  # only the first import counted, not the duplicate


def test_budget_without_category_absent_from_status(client):
    checking_id = _create_account(client, "Checking", "checking")
    _import_csv(
        client, "march.csv",
        b"Date,Description,Amount\n"
        b"2026-03-05,REWE Supermarket,-50.00\n"
        b"2026-03-06,Netflix,-12.99\n",
        checking_id,
    )
    client.put("/api/budgets/Groceries", json={"amount_minor": 10000, "currency": "EUR"})

    status = client.get("/api/budgets/status", params={"month": "2026-03"}).json()
    categories = [item["category"] for item in status["items"]]
    assert categories == ["Groceries"]  # Subscriptions has no budget -> not itemized


def test_invalid_month_format_returns_422(client):
    r = client.get("/api/budgets/status", params={"month": "not-a-month"})
    assert r.status_code == 422
