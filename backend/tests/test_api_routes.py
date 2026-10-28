from __future__ import annotations

import io


def test_duplicate_account_name_returns_409(client):
    r1 = client.post("/api/accounts", json={"name": "Checking", "account_type": "checking", "currency": "EUR"})
    assert r1.status_code == 200
    r2 = client.post("/api/accounts", json={"name": "Checking", "account_type": "savings", "currency": "EUR"})
    assert r2.status_code == 409


def test_account_list_includes_transaction_count_and_balance(client):
    r = client.post("/api/accounts", json={"name": "Checking", "account_type": "checking", "currency": "EUR"})
    account_id = r.json()["id"]
    assert r.json()["transaction_count"] == 0
    assert r.json()["current_balance_minor"] == 0

    csv_content = b"Date,Description,Amount\n2026-04-01,Groceries,-32.40\n2026-04-05,Salary,2500.00\n"
    files = {"file": ("april.csv", io.BytesIO(csv_content), "text/csv")}
    preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id}).json()
    client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": account_id})

    r = client.get("/api/accounts")
    account = next(a for a in r.json() if a["id"] == account_id)
    assert account["transaction_count"] == 2
    assert account["current_balance_minor"] == -3240 + 250000


def test_account_balance_excludes_duplicates(client):
    r = client.post("/api/accounts", json={"name": "Checking", "account_type": "checking", "currency": "EUR"})
    account_id = r.json()["id"]

    csv_content = b"Date,Description,Amount\n2026-04-01,Test,-10.00\n"
    files = {"file": ("x.csv", io.BytesIO(csv_content), "text/csv")}
    preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id}).json()
    client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": account_id})

    # Re-upload the same content under a different filename so it isn't
    # rejected at the file-checksum level, but IS caught as a transaction
    # duplicate and excluded from the balance.
    csv_content2 = b"Date,Description,Amount\n2026-04-01,Test,-10.00\n2026-04-02,Other,-5.00\n"
    files2 = {"file": ("y.csv", io.BytesIO(csv_content2), "text/csv")}
    preview2 = client.post("/api/imports/preview", files=files2, data={"account_id": account_id}).json()
    client.post("/api/imports/commit", json={"staging_id": preview2["staging_id"], "account_id": account_id})

    r = client.get("/api/accounts")
    account = next(a for a in r.json() if a["id"] == account_id)
    assert account["transaction_count"] == 2  # the -10.00 duplicate excluded, -5.00 counted
    assert account["current_balance_minor"] == -1500


def test_update_account_name_and_currency(client):
    r = client.post("/api/accounts", json={"name": "Old Name", "account_type": "checking", "currency": "EUR"})
    account_id = r.json()["id"]

    r = client.patch(f"/api/accounts/{account_id}", json={"name": "New Name", "currency": "USD"})
    assert r.status_code == 200
    assert r.json()["name"] == "New Name"
    assert r.json()["currency"] == "USD"


def test_archive_account_excludes_from_default_list(client):
    r = client.post("/api/accounts", json={"name": "Old Account", "account_type": "checking", "currency": "EUR"})
    account_id = r.json()["id"]

    client.patch(f"/api/accounts/{account_id}", json={"is_archived": True})

    r = client.get("/api/accounts")
    assert account_id not in [a["id"] for a in r.json()]

    r = client.get("/api/accounts", params={"include_archived": True})
    assert account_id in [a["id"] for a in r.json()]


def test_update_nonexistent_account_returns_404(client):
    r = client.patch("/api/accounts/9999", json={"name": "Ghost"})
    assert r.status_code == 404


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200


def test_create_and_list_accounts(client):
    r = client.post("/api/accounts", json={"name": "Checking Account", "account_type": "checking", "currency": "EUR"})
    assert r.status_code == 200, r.text
    account = r.json()
    assert account["name"] == "Checking Account"

    r = client.get("/api/accounts")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_import_preview_then_commit_then_list_transactions(client):
    r = client.post("/api/accounts", json={"name": "Checking Account", "account_type": "checking", "currency": "EUR"})
    account_id = r.json()["id"]

    csv_content = b"Date,Description,Amount\n2026-04-01,Lidl Supermarket,-32.40\n2026-04-05,Salary,2500.00\n"
    files = {"file": ("april.csv", io.BytesIO(csv_content), "text/csv")}
    r = client.post("/api/imports/preview", files=files, data={"account_id": account_id})
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["transaction_count"] == 2
    assert not preview["ambiguous"]

    r = client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": account_id})
    assert r.status_code == 200, r.text
    commit = r.json()
    assert commit["transactions_created"] == 2

    r = client.get("/api/transactions")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["items"][0]["source_filename"] == "april.csv"


def test_duplicate_commit_returns_409(client):
    r = client.post("/api/accounts", json={"name": "Checking", "account_type": "checking", "currency": "EUR"})
    account_id = r.json()["id"]

    csv_content = b"Date,Description,Amount\n2026-04-01,Test,-10.00\n"

    files = {"file": ("x.csv", io.BytesIO(csv_content), "text/csv")}
    preview1 = client.post("/api/imports/preview", files=files, data={"account_id": account_id}).json()
    client.post("/api/imports/commit", json={"staging_id": preview1["staging_id"], "account_id": account_id})

    files = {"file": ("x.csv", io.BytesIO(csv_content), "text/csv")}
    preview2 = client.post("/api/imports/preview", files=files, data={"account_id": account_id}).json()
    r = client.post("/api/imports/commit", json={"staging_id": preview2["staging_id"], "account_id": account_id})
    assert r.status_code == 409


def test_reject_unsupported_file_type(client):
    r = client.post("/api/accounts", json={"name": "Checking", "account_type": "checking", "currency": "EUR"})
    account_id = r.json()["id"]
    files = {"file": ("malware.exe", io.BytesIO(b"whatever"), "application/octet-stream")}
    r = client.post("/api/imports/preview", files=files, data={"account_id": account_id})
    assert r.status_code == 400


def test_transaction_filters_and_pagination(client):
    r = client.post("/api/accounts", json={"name": "Checking", "account_type": "checking", "currency": "EUR"})
    account_id = r.json()["id"]

    csv_content = (
        b"Date,Description,Amount\n"
        b"2026-04-01,Lidl Supermarket,-32.40\n"
        b"2026-04-05,Salary,2500.00\n"
        b"2026-04-10,Amazon.de,-89.10\n"
    )
    files = {"file": ("april.csv", io.BytesIO(csv_content), "text/csv")}
    preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id}).json()
    client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": account_id})

    r = client.get("/api/transactions", params={"category": "Groceries"})
    assert r.status_code == 200
    assert r.json()["total"] == 1

    r = client.get("/api/transactions", params={"page": 1, "page_size": 2})
    assert len(r.json()["items"]) == 2
    assert r.json()["total"] == 3


def test_update_transaction_category_persists_correction(client):
    r = client.post("/api/accounts", json={"name": "Checking", "account_type": "checking", "currency": "EUR"})
    account_id = r.json()["id"]

    csv_content = b"Date,Description,Amount\n2026-04-01,Mystery Shop,-10.00\n"
    files = {"file": ("x.csv", io.BytesIO(csv_content), "text/csv")}
    preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id}).json()
    client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": account_id})

    tx_id = client.get("/api/transactions").json()["items"][0]["id"]

    r = client.patch(f"/api/transactions/{tx_id}", json={"category": "Travel"})
    assert r.status_code == 200
    assert r.json()["category"] == "Travel"


def test_analytics_totals_endpoint(client):
    r = client.post("/api/accounts", json={"name": "Checking", "account_type": "checking", "currency": "EUR"})
    account_id = r.json()["id"]

    csv_content = b"Date,Description,Amount\n2026-04-01,Test,-10.00\n2026-04-02,Salary,100.00\n"
    files = {"file": ("x.csv", io.BytesIO(csv_content), "text/csv")}
    preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id}).json()
    client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": account_id})

    r = client.get("/api/analytics/totals")
    assert r.status_code == 200
    body = r.json()
    assert body["income_minor"] == 10000
    assert body["expenses_minor"] == 1000
    assert body["net_minor"] == 9000


def test_import_history_endpoint(client):
    r = client.post("/api/accounts", json={"name": "Checking", "account_type": "checking", "currency": "EUR"})
    account_id = r.json()["id"]

    csv_content = b"Date,Description,Amount\n2026-04-01,Test,-10.00\n"
    files = {"file": ("x.csv", io.BytesIO(csv_content), "text/csv")}
    preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id}).json()
    client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": account_id})

    r = client.get("/api/imports")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["filename"] == "x.csv"


def test_system_info_tells_when_a_restart_is_needed(client, monkeypatch):
    import app.api.routes.system as system

    assert client.get("/api/system/info").json()["restart_needed"] is False
    monkeypatch.setattr(system, "_STARTED_WITH", system._code_stamp() - 10)  # code changed after the start
    assert client.get("/api/system/info").json()["restart_needed"] is True
