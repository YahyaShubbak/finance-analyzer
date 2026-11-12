"""Tests for spec Milestone 3 sections 3-4: turning a transaction
correction into a persisted, reusable rule that takes priority over
built-in defaults for future imports, without ever overwriting a
subsequent explicit correction.
"""
from __future__ import annotations

import io


def _create_account(client, name="Checking"):
    r = client.post("/api/accounts", json={"name": name, "account_type": "checking", "currency": "EUR"})
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


def _first_transaction(client):
    return client.get("/api/transactions").json()["items"][0]


# ---------------------------------------------------------------------------
# Merchant rules
# ---------------------------------------------------------------------------

def test_merchant_rule_persists_and_applies_immediately(client):
    account_id = _create_account(client)
    _import_csv(client, "a.csv", b"Date,Description,Amount\n2026-01-01,XYZ Mktp DE*AB1234,-42.00\n", account_id)
    tx = _first_transaction(client)
    assert tx["merchant"] != "MyStore"  # not already normalized to this by defaults

    r = client.post(f"/api/transactions/{tx['id']}/merchant-rule", json={"normalized_merchant": "MyStore"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["transaction"]["merchant"] == "MyStore"
    assert body["merchant_rule"]["normalized_merchant"] == "MyStore"
    assert body["merchant_rule"]["is_user_defined"] is True

    reloaded = client.get("/api/transactions").json()["items"][0]
    assert reloaded["merchant"] == "MyStore"


def test_merchant_rule_applies_to_future_import_with_different_suffix(client):
    account_id = _create_account(client)
    _import_csv(client, "a.csv", b"Date,Description,Amount\n2026-01-01,XYZ Mktp DE*AB1234,-42.00\n", account_id)
    tx = _first_transaction(client)
    client.post(f"/api/transactions/{tx['id']}/merchant-rule", json={"normalized_merchant": "MyStore"})

    # A different order code, same merchant pattern.
    _import_csv(client, "b.csv", b"Date,Description,Amount\n2026-02-01,XYZ Mktp DE*XY9999,-15.00\n", account_id)

    items = client.get("/api/transactions").json()["items"]
    new_tx = next(t for t in items if t["normalized_description"] == "XYZ Mktp DE*XY9999")
    assert new_tx["merchant"] == "MyStore"


def test_merchant_rule_overrides_default_normalization(client):
    """A user rule takes priority over an existing built-in rule (spec:
    explicit user rule > existing deterministic rule > default)."""
    account_id = _create_account(client)
    _import_csv(client, "a.csv", b"Date,Description,Amount\n2026-01-01,Netflix.com,-19.99\n", account_id)
    tx = _first_transaction(client)
    assert tx["merchant"] == "Netflix"  # the built-in default rule applies first

    # User decides they want it labeled differently.
    client.post(f"/api/transactions/{tx['id']}/merchant-rule", json={"normalized_merchant": "Streaming - Netflix"})

    _import_csv(client, "b.csv", b"Date,Description,Amount\n2026-02-01,Netflix.com,-19.99\n", account_id)
    items = client.get("/api/transactions").json()["items"]
    newest = next(t for t in items if t["normalized_description"] == "Netflix.com" and t["id"] != tx["id"])
    assert newest["merchant"] == "Streaming - Netflix"


# ---------------------------------------------------------------------------
# Category rules
# ---------------------------------------------------------------------------

def test_category_rule_persists_and_applies_immediately(client):
    account_id = _create_account(client)
    _import_csv(client, "a.csv", b"Date,Description,Amount\n2026-01-01,Totally Unknown Vendor,-10.00\n", account_id)
    tx = _first_transaction(client)
    assert tx["needs_review"] is True

    r = client.post(f"/api/transactions/{tx['id']}/category-rule", json={"category": "Entertainment"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["transaction"]["category"] == "Entertainment"
    assert body["transaction"]["needs_review"] is False
    assert body["category_rule"]["category"] == "Entertainment"
    assert body["category_rule"]["match_field"] == "merchant"  # fallback merchant cleanup still produces a usable merchant string


def test_category_rule_applies_to_future_matching_transaction(client):
    account_id = _create_account(client)
    _import_csv(client, "a.csv", b"Date,Description,Amount\n2026-01-01,Amazon.de,-42.00\n", account_id)
    tx = _first_transaction(client)
    assert tx["merchant"] == "Amazon"

    client.post(f"/api/transactions/{tx['id']}/category-rule", json={"category": "Household"})

    _import_csv(client, "b.csv", b"Date,Description,Amount\n2026-02-01,Amazon.de,-15.00\n", account_id)
    items = client.get("/api/transactions").json()["items"]
    newest = next(t for t in items if t["amount_minor"] == -1500)
    assert newest["category"] == "Household"


def test_explicit_correction_not_overwritten_by_later_rule(client):
    """If a specific transaction was individually corrected, creating a
    NEW rule afterward for a different transaction must not silently
    change the already-corrected one."""
    account_id = _create_account(client)
    _import_csv(
        client, "a.csv",
        b"Date,Description,Amount\n"
        b"2026-01-01,Amazon.de,-42.00\n"
        b"2026-01-02,Amazon.de,-15.00\n",
        account_id,
    )
    items = client.get("/api/transactions").json()["items"]
    tx_a = next(t for t in items if t["amount_minor"] == -4200)
    tx_b = next(t for t in items if t["amount_minor"] == -1500)

    # tx_a gets an individual, direct correction (not via rule creation).
    client.patch(f"/api/transactions/{tx_a['id']}", json={"category": "Gifts"})

    # A rule is created FROM tx_b afterward.
    client.post(f"/api/transactions/{tx_b['id']}/category-rule", json={"category": "Shopping"})

    tx_a_after = next(t for t in client.get("/api/transactions").json()["items"] if t["id"] == tx_a["id"])
    assert tx_a_after["category"] == "Gifts"  # untouched by the later rule creation


def test_merchant_rule_strips_short_trailing_reference_numbers(client):
    """Regression test: a trailing reference number as short as 2 digits
    must still be stripped so the rule generalizes to future imports with
    a different reference number (found via live smoke testing)."""
    account_id = _create_account(client)
    _import_csv(client, "a.csv", b"Date,Description,Amount\n2026-01-01,Local Cafe 123,-9.20\n", account_id)
    tx = _first_transaction(client)

    r = client.post(f"/api/transactions/{tx['id']}/merchant-rule", json={"normalized_merchant": "Local Cafe"})
    assert r.json()["merchant_rule"]["pattern"] == "Local Cafe"

    _import_csv(client, "b.csv", b"Date,Description,Amount\n2026-02-01,Local Cafe 456,-8.50\n", account_id)
    items = client.get("/api/transactions").json()["items"]
    newest = next(t for t in items if t["normalized_description"] == "Local Cafe 456")
    assert newest["merchant"] == "Local Cafe"


def test_rule_creation_on_unknown_transaction_returns_404(client):
    r = client.post("/api/transactions/9999/merchant-rule", json={"normalized_merchant": "X"})
    assert r.status_code == 404
    r = client.post("/api/transactions/9999/category-rule", json={"category": "X"})
    assert r.status_code == 404


def test_creating_same_merchant_rule_twice_does_not_duplicate(client):
    account_id = _create_account(client)
    _import_csv(client, "a.csv", b"Date,Description,Amount\n2026-01-01,AMZN Mktp DE*AB1234,-42.00\n", account_id)
    tx = _first_transaction(client)

    r1 = client.post(f"/api/transactions/{tx['id']}/merchant-rule", json={"normalized_merchant": "Amazon"})
    rule_id_1 = r1.json()["merchant_rule"]["id"]

    r2 = client.post(f"/api/transactions/{tx['id']}/merchant-rule", json={"normalized_merchant": "Amazon"})
    rule_id_2 = r2.json()["merchant_rule"]["id"]

    assert rule_id_1 == rule_id_2  # same pattern re-used, not duplicated


def test_merchant_rule_reaches_bookings_that_name_the_payee_only_in_their_payee_column(client):
    """Only the bookings the pattern occurs in are looked at; the payee column is kept with the
    raw row, not in the description."""
    account_id = _create_account(client)
    _import_csv(client, "giro.csv", (
        b"Date,Name,Description,Amount\n"
        b"2026-03-01,Kiosk Sonnenschein,Einkauf eins,-4.50\n"
        b"2026-03-02,Kiosk Sonnenschein,Einkauf zwei,-7.20\n"
        b"2026-03-03,Kiosk Mondschein,Einkauf drei,-3.00\n"
    ), account_id)
    items = {t["amount_minor"]: t for t in client.get("/api/transactions").json()["items"]}

    r = client.post(f"/api/transactions/{items[-450]['id']}/merchant-rule", json={"normalized_merchant": "Sonnenkiosk"})
    assert r.status_code == 200, r.text
    assert r.json()["applied_to"] == 1

    items = {t["amount_minor"]: t for t in client.get("/api/transactions").json()["items"]}
    assert items[-450]["merchant"] == items[-720]["merchant"] == "Sonnenkiosk"
    assert items[-300]["merchant"] != "Sonnenkiosk"


def test_merchant_rule_for_a_name_with_quotes_still_reaches_its_other_bookings(client):
    account_id = _create_account(client)
    _import_csv(client, "giro.csv", (
        b"Date,Name,Description,Amount\n"
        b'2026-03-01,"Kiosk ""Zur Sonne""",Einkauf eins,-4.50\n'
        b'2026-03-02,"Kiosk ""Zur Sonne""",Einkauf zwei,-7.20\n'
    ), account_id)
    items = {t["amount_minor"]: t for t in client.get("/api/transactions").json()["items"]}

    r = client.post(f"/api/transactions/{items[-450]['id']}/merchant-rule", json={"normalized_merchant": "Sonnenkiosk"})
    assert r.status_code == 200, r.text
    assert r.json()["applied_to"] == 1
