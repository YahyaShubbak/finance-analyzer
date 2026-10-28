"""Review queue grouped by payee; starting over. Invented data."""
from __future__ import annotations

import io


def _import_csv(client, rows: str, name="giro.csv"):
    account = client.post("/api/accounts", json={"name": "Giro", "account_type": "checking"}).json()["id"]
    body = ("Datum,Beschreibung,Betrag\n" + rows).encode()
    preview = client.post("/api/imports/preview", data={"account_id": account},
                          files={"file": (name, io.BytesIO(body), "text/csv")}).json()
    r = client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": account})
    assert r.status_code == 200, r.text
    return account


ROWS = "".join(f"2026-03-{d:02d},Lastschrift Kiosk Sonnenschein Einkauf {d},-{d}.50\n" for d in range(1, 6)) \
    + "".join(f"2026-03-{d:02d},Lastschrift Werkstatt Muster Rechnung {d},-{d}0.00\n" for d in range(10, 12)) \
    + "2026-03-20,Lastschrift Bastelladen Beispiel,-7.00\n"


def test_the_biggest_groups_of_a_payee_come_first(client):
    _import_csv(client, ROWS)
    data = client.get("/api/transactions/review-groups").json()
    assert data["total_transactions"] == 8
    groups = data["groups"]
    assert [g["count"] for g in groups] == [5, 2, 1]
    assert "Kiosk Sonnenschein" in groups[0]["label"] and groups[0]["learnable"]
    assert groups[0]["total_minor"] == -(150 + 250 + 350 + 450 + 550)
    assert all(t["needs_review"] for g in groups for t in g["transactions"])
    assert client.get("/api/transactions/review-groups", params={"page_size": 2, "page": 2}).json()["groups"][0]["count"] == 1


def test_a_huge_group_lists_its_newest_bookings_and_all_ids(client, monkeypatch):
    from app.api.routes import transactions as route

    monkeypatch.setattr(route, "MAX_GROUP_DETAILS", 3)
    _import_csv(client, ROWS)
    group = client.get("/api/transactions/review-groups").json()["groups"][0]
    assert group["count"] == 5 and len(group["member_ids"]) == 5
    assert [t["transaction_date"] for t in group["transactions"]] == ["2026-03-05", "2026-03-04", "2026-03-03"]
    r = client.post("/api/transactions/assign-category", json={
        "transaction_ids": group["member_ids"], "category": "Groceries", "learn": False})
    assert r.json()["updated"] == 5


def test_one_category_for_a_whole_group(client):
    _import_csv(client, ROWS)
    group = client.get("/api/transactions/review-groups").json()["groups"][0]
    ids = [t["id"] for t in group["transactions"]][:4]  # the user left one out
    left_out = group["transactions"][4]["id"]
    r = client.post("/api/transactions/assign-category", json={
        "transaction_ids": ids, "category": "Groceries", "learn": True, "leave_out": [left_out]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated"] == 4 and body["rule"]["category"] == "Groceries"
    assert body["applied_to"] == 0  # the one left out is not sorted by the rule
    remaining = client.get("/api/transactions/review-groups").json()
    assert remaining["total_transactions"] == 4
    assert left_out in [t["id"] for g in remaining["groups"] for t in g["transactions"]]

    r = client.post("/api/transactions/assign-category", json={"transaction_ids": [999999], "category": "Groceries"})
    assert r.status_code == 404
    assert client.post("/api/transactions/assign-category", json={"transaction_ids": [], "category": "x"}).status_code == 422


def test_reset_deletes_everything_but_the_backups(client):
    from app.config import settings

    _import_csv(client, ROWS)
    assert client.post("/api/categories", json={"name": "Eigene Kategorie"}).status_code == 200
    assert client.post("/api/backup/create").status_code == 200
    backups_before = list(settings.backups_dir.iterdir())
    assert any(settings.imports_dir.iterdir())

    assert client.post("/api/system/reset", json={"confirm": "yes"}).status_code == 422  # must be typed exactly
    r = client.post("/api/system/reset", json={"confirm": "RESET"})
    assert r.status_code == 200, r.text
    assert client.get("/api/accounts").json() == []
    assert client.get("/api/transactions").json()["total"] == 0
    assert client.get("/api/imports").json() == []
    assert "Eigene Kategorie" not in str(client.get("/api/categories").json())
    assert not any(settings.imports_dir.iterdir())
    assert list(settings.backups_dir.iterdir()) == backups_before
    # the app works on afterwards
    _import_csv(client, ROWS, "again.csv")
    assert client.get("/api/transactions").json()["total"] == 8


def test_reset_can_delete_the_backups_too(client):
    from app.config import settings

    (settings.backups_dir / "old.zip").write_bytes(b"x")
    assert client.post("/api/system/reset", json={"confirm": "RESET", "delete_backups": True}).status_code == 200
    assert not any(settings.backups_dir.iterdir())


def test_transactions_can_be_sorted_by_amount_account_and_type(client):
    giro = _import_csv(client, ROWS)
    other = client.post("/api/accounts", json={"name": "Anderes Konto", "account_type": "savings"}).json()["id"]
    body = b"Datum,Beschreibung,Betrag\n2026-03-15,Zinsgutschrift Beispielbank,12.00\n"
    preview = client.post("/api/imports/preview", data={"account_id": other},
                          files={"file": ("spar.csv", io.BytesIO(body), "text/csv")}).json()
    client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": other})

    def listed(**params):
        return client.get("/api/transactions", params={"page_size": 100, **params}).json()["items"]

    amounts = [t["amount_minor"] for t in listed(sort="amount", order="asc")]
    assert amounts == sorted(amounts) and amounts[0] == -11000
    assert [t["amount_minor"] for t in listed(sort="amount", order="desc")][0] == 1200
    assert [t["account_name"] for t in listed(sort="account", order="asc")][0] == "Anderes Konto"
    assert [t["account_name"] for t in listed(sort="account", order="desc")][0] == "Giro"
    types = [t["transaction_type"] for t in listed(sort="type", order="asc")]
    assert types == sorted(types)
    dates = [t["transaction_date"] for t in listed()]
    assert dates == sorted(dates, reverse=True) and giro
    assert client.get("/api/transactions", params={"sort": "merchant"}).status_code == 422


def test_bookings_left_out_of_a_group_stay_out_when_rules_run_again(client):
    _import_csv(client, ROWS)
    group = client.get("/api/transactions/review-groups").json()["groups"][0]
    ids = [t["id"] for t in group["transactions"]]
    left_out = ids[-1]
    r = client.post("/api/transactions/assign-category",
                    json={"transaction_ids": ids[:-1], "category": "Groceries", "learn": False, "leave_out": [left_out]})
    assert r.status_code == 200
    assert client.post("/api/transactions/reapply-rules").status_code == 200
    tx = next(t for t in client.get("/api/transactions", params={"page_size": 100}).json()["items"] if t["id"] == left_out)
    assert tx["category"] != "Groceries" and tx["needs_review"]
