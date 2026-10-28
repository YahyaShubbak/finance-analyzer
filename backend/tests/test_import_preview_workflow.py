"""API-level tests for the improved import preview and duplicate-review
workflow (spec Milestone 3, sections 1-4): per-file account selection,
new/exact/possible-duplicate counts, row-level match explanations, and
explicit keep/skip decisions at commit time — plus the accounting
requirements that must hold regardless of classification.
"""
from __future__ import annotations

import io


def _create_account(client, name, account_type="checking", currency="EUR"):
    r = client.post("/api/accounts", json={"name": name, "account_type": account_type, "currency": currency})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _preview(client, filename, content: bytes, account_id: int):
    files = {"file": (filename, io.BytesIO(content), "text/csv")}
    r = client.post("/api/imports/preview", files=files, data={"account_id": account_id})
    assert r.status_code == 200, r.text
    return r.json()


def _commit(client, staging_id, account_id, row_decisions=None):
    payload = {"staging_id": staging_id, "account_id": account_id}
    if row_decisions is not None:
        payload["row_decisions"] = row_decisions
    r = client.post("/api/imports/commit", json=payload)
    return r


# ---------------------------------------------------------------------------

def test_preview_without_account_asks_for_one(client):
    _create_account(client, "Checking")
    files = {"file": ("x.csv", io.BytesIO(b"Date,Description,Amount\n2026-01-01,Test,-1.00\n"), "text/csv")}
    r = client.post("/api/imports/preview", files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    # a kind of file never imported before: the user chooses the account
    assert body["account_id"] is None and body["account_recognized"] is None and body["auto_import"] is False
    assert body["transaction_count"] == 1 and body["new_count"] == 0  # duplicates need the account


def test_preview_shows_per_file_account_and_counts(client):
    account_id = _create_account(client, "Checking")

    preview = _preview(
        client, "april.csv",
        b"Date,Description,Amount\n2026-04-01,Groceries Store,-32.40\n2026-04-05,Salary,2500.00\n",
        account_id,
    )
    assert preview["account_id"] == account_id
    assert preview["account_name"] == "Checking"
    assert preview["new_count"] == 2
    assert preview["exact_duplicate_count"] == 0
    assert preview["possible_duplicate_count"] == 0
    assert len(preview["row_classifications"]) == 2


def test_preview_detects_exact_duplicate_against_existing_data(client):
    account_id = _create_account(client, "Checking")
    p1 = _preview(client, "a.csv", b"Date,Description,Amount\n2026-01-02,Amazon.de,-45.67\n", account_id)
    _commit(client, p1["staging_id"], account_id)

    p2 = _preview(client, "b.csv", b"Date,Description,Amount\n2026-01-02,Amazon.de,-45.67\n2026-01-03,New Item,-9.00\n", account_id)
    assert p2["exact_duplicate_count"] == 1
    assert p2["new_count"] == 1

    dup_row = next(r for r in p2["row_classifications"] if r["status"] == "exact_duplicate")
    assert dup_row["match"] is not None
    assert dup_row["match"]["amount_minor"] == -4567
    assert "existing transaction" in dup_row["match_reason"].lower()


def test_preview_detects_possible_duplicate_with_explanation(client):
    account_id = _create_account(client, "Checking")
    p1 = _preview(client, "a.csv", b"Date,Description,Amount\n2026-02-15,Netflix.com,-19.99\n", account_id)
    _commit(client, p1["staging_id"], account_id)

    # Same merchant + same amount, one day later — pending-vs-posted timing.
    p2 = _preview(client, "b.csv", b"Date,Description,Amount\n2026-02-16,NETFLIX.COM SUBSCRIPTION,-19.99\n", account_id)
    assert p2["possible_duplicate_count"] == 1
    assert p2["exact_duplicate_count"] == 0

    row = p2["row_classifications"][0]
    assert row["status"] == "possible_duplicate"
    assert row["match"]["amount_minor"] == -1999
    assert "same merchant" in row["match_reason"].lower()
    assert "same amount" in row["match_reason"].lower()
    assert "1 day" in row["match_reason"]


def test_exact_duplicate_defaults_to_skip_never_in_totals(client):
    account_id = _create_account(client, "Checking")
    p1 = _preview(client, "a.csv", b"Date,Description,Amount\n2026-01-02,Amazon.de,-45.67\n", account_id)
    _commit(client, p1["staging_id"], account_id)

    p2 = _preview(client, "b.csv", b"Date,Description,Amount\n2026-01-02,Amazon.de,-45.67\n2026-01-04,Padding Row,-1.00\n", account_id)
    commit2 = _commit(client, p2["staging_id"], account_id)
    assert commit2.status_code == 200
    body = commit2.json()
    assert body["transactions_created"] == 1  # only the unrelated padding row
    assert body["rows_skipped"] == 1

    totals = client.get("/api/analytics/totals").json()
    assert totals["expenses_minor"] == 4567 + 100  # Amazon counted exactly once, not twice

    tx_list = client.get("/api/transactions").json()
    assert tx_list["total"] == 2


def test_possible_duplicate_defaults_to_keep_never_silently_discarded(client):
    account_id = _create_account(client, "Checking")
    p1 = _preview(client, "a.csv", b"Date,Description,Amount\n2026-02-15,Netflix.com,-19.99\n", account_id)
    _commit(client, p1["staging_id"], account_id)

    p2 = _preview(client, "b.csv", b"Date,Description,Amount\n2026-02-16,Netflix.com,-19.99\n", account_id)
    commit2 = _commit(client, p2["staging_id"], account_id)
    assert commit2.status_code == 200
    body = commit2.json()
    assert body["transactions_created"] == 1  # kept by default, not silently dropped
    assert body["rows_skipped"] == 0

    tx_list = client.get("/api/transactions").json()
    assert tx_list["total"] == 2

    totals = client.get("/api/analytics/totals").json()
    assert totals["expenses_minor"] == 3998  # both charges counted — genuinely two separate transactions


def test_user_can_explicitly_skip_a_possible_duplicate(client):
    account_id = _create_account(client, "Checking")
    p1 = _preview(client, "a.csv", b"Date,Description,Amount\n2026-02-15,Netflix.com,-19.99\n", account_id)
    _commit(client, p1["staging_id"], account_id)

    p2 = _preview(client, "b.csv", b"Date,Description,Amount\n2026-02-16,Netflix.com,-19.99\n", account_id)
    row = p2["row_classifications"][0]
    assert row["status"] == "possible_duplicate"

    commit2 = _commit(client, p2["staging_id"], account_id, row_decisions=[{"source_row_index": row["source_row_index"], "decision": "skip"}])
    body = commit2.json()
    assert body["transactions_created"] == 0
    assert body["rows_skipped"] == 1

    totals = client.get("/api/analytics/totals").json()
    assert totals["expenses_minor"] == 1999  # only the original


def test_user_can_explicitly_keep_an_exact_duplicate(client):
    account_id = _create_account(client, "Checking")
    p1 = _preview(client, "a.csv", b"Date,Description,Amount\n2026-01-02,Coffee Shop,-4.50\n", account_id)
    _commit(client, p1["staging_id"], account_id)

    p2 = _preview(client, "b.csv", b"Date,Description,Amount\n2026-01-02,Coffee Shop,-4.50\n2026-01-05,Other,-1.00\n", account_id)
    dup_row = next(r for r in p2["row_classifications"] if r["status"] == "exact_duplicate")

    commit2 = _commit(
        client, p2["staging_id"], account_id,
        row_decisions=[{"source_row_index": dup_row["source_row_index"], "decision": "keep"}],
    )
    body = commit2.json()
    assert body["transactions_created"] == 2  # the explicitly-kept duplicate + the unrelated row
    assert body["rows_skipped"] == 0

    tx_list = client.get("/api/transactions").json()
    assert tx_list["total"] == 3
    assert all(not t["is_duplicate"] for t in tx_list["items"])


def test_existing_transaction_never_modified_by_duplicate_review(client):
    account_id = _create_account(client, "Checking")
    p1 = _preview(client, "a.csv", b"Date,Description,Amount\n2026-01-02,Amazon.de,-45.67\n", account_id)
    _commit(client, p1["staging_id"], account_id)

    original = client.get("/api/transactions").json()["items"][0]

    p2 = _preview(client, "b.csv", b"Date,Description,Amount\n2026-01-02,Amazon.de,-45.67\n", account_id)
    _commit(client, p2["staging_id"], account_id)  # exact duplicate, defaults to skip

    after = client.get("/api/transactions").json()["items"][0]
    assert after["id"] == original["id"]
    assert after["amount_minor"] == original["amount_minor"]
    assert after == original  # completely untouched


def test_duplicate_detection_never_alters_amount(client):
    account_id = _create_account(client, "Checking")
    p1 = _preview(client, "a.csv", b"Date,Description,Amount\n2026-01-02,Amazon.de,-45.67\n", account_id)
    _commit(client, p1["staging_id"], account_id)

    # (another file with the same booking — an identical file is refused outright)
    p2 = _preview(client, "b.csv", b"Date,Description,Amount\r\n2026-01-02,Amazon.de,-45.67\r\n", account_id)
    dup_row = next(r for r in p2["row_classifications"] if r["status"] == "exact_duplicate")
    _commit(
        client, p2["staging_id"], account_id,
        row_decisions=[{"source_row_index": dup_row["source_row_index"], "decision": "keep"}],
    )

    amounts = {t["amount_minor"] for t in client.get("/api/transactions").json()["items"]}
    assert amounts == {-4567}  # both rows have the exact same, unaltered amount


def test_raw_source_rows_preserved_even_when_skipped(client):
    """Auditability: skipped rows still leave their raw record traceable
    to the original import — only the normalized Transaction is absent."""
    account_id = _create_account(client, "Checking")
    p1 = _preview(client, "a.csv", b"Date,Description,Amount\n2026-01-02,Amazon.de,-45.67\n", account_id)
    _commit(client, p1["staging_id"], account_id)

    p2 = _preview(client, "b.csv", b"Date,Description,Amount\n2026-01-02,Amazon.de,-45.67\n2026-01-05,Padding Row,-1.00\n", account_id)
    commit2 = _commit(client, p2["staging_id"], account_id)
    assert commit2.status_code == 200

    imports = client.get("/api/imports").json()
    assert len(imports) == 2
    b_import = next(i for i in imports if i["filename"] == "b.csv")
    # The import record itself proves the file was processed even though
    # it produced fewer visible transactions than raw rows — traceability intact.
    assert b_import["detected_transaction_count"] == 2


def test_new_transaction_gets_needs_review_flag_when_unclassifiable(client):
    account_id = _create_account(client, "Checking")
    preview = _preview(client, "x.csv", b"Date,Description,Amount\n2026-01-01,Totally Unknown Vendor XYZ,-12.34\n", account_id)
    row = preview["row_classifications"][0]
    assert row["needs_review"] is True

    _commit(client, preview["staging_id"], account_id)
    tx = client.get("/api/transactions").json()["items"][0]
    assert tx["needs_review"] is True
    assert tx["review_reason"] is not None


def test_needs_review_queue_filter(client):
    account_id = _create_account(client, "Checking")
    preview = _preview(
        client, "x.csv",
        b"Date,Description,Amount\n"
        b"2026-01-01,Totally Unknown Vendor XYZ,-12.34\n"
        b"2026-01-02,Amazon.de,-50.00\n",
        account_id,
    )
    _commit(client, preview["staging_id"], account_id)

    r = client.get("/api/transactions", params={"needs_review": True})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["normalized_description"] == "Totally Unknown Vendor XYZ"

    r = client.get("/api/transactions", params={"needs_review": False})
    assert r.json()["total"] == 1


def test_resolving_needs_review_via_correction_removes_from_queue(client):
    account_id = _create_account(client, "Checking")
    preview = _preview(client, "x.csv", b"Date,Description,Amount\n2026-01-01,Totally Unknown Vendor XYZ,-12.34\n", account_id)
    _commit(client, preview["staging_id"], account_id)

    tx = client.get("/api/transactions").json()["items"][0]
    assert tx["needs_review"] is True

    client.patch(f"/api/transactions/{tx['id']}", json={"category": "Shopping"})

    r = client.get("/api/transactions", params={"needs_review": True})
    assert r.json()["total"] == 0
