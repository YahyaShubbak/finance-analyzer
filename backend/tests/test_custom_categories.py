"""Categories the user creates next to the built-in ones: usable everywhere
(transactions, learned rules, budgets); renaming and deleting carry along
what refers to them by name."""
from __future__ import annotations

import io


def _setup(client):
    account = client.post("/api/accounts", json={"name": "Giro", "account_type": "checking"}).json()["id"]
    csv = (b"Date,Description,Amount\n2026-03-01,Bank Kredit Rate 03,-250.00\n"
           b"2026-04-01,Bank Kredit Rate 04,-250.00\n2026-04-03,Kiosk,-3.00\n")
    preview = client.post("/api/imports/preview", files={"file": ("g.csv", io.BytesIO(csv), "text/csv")},
                          data={"account_id": account}).json()
    client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": account})
    return {t["amount_minor"]: t for t in client.get("/api/transactions").json()["items"]}


def _custom(client):
    return [c for c in client.get("/api/categories").json() if not c["built_in"]]


def test_create_use_rename_delete(client):
    tx = _setup(client)
    created = client.post("/api/categories", json={"name": "  Darlehen "})
    assert created.status_code == 200, created.text
    cat = created.json()
    assert cat["name"] == "Darlehen" and not cat["built_in"]
    assert any(c["name"] == "Food" and c["built_in"] for c in client.get("/api/categories").json())

    loan = next(t for t in tx.values() if "Kredit" in t["normalized_description"])
    lesson = client.post(f"/api/transactions/{loan['id']}/category-rule", json={"category": "Darlehen"}).json()
    assert lesson["applied_to"] == 1  # the other installment
    client.put("/api/budgets/Darlehen", json={"amount_minor": 25000, "currency": "EUR"})
    assert _custom(client)[0]["transaction_count"] == 2

    renamed = client.patch(f"/api/categories/{cat['id']}", json={"name": "Kredit"})
    assert renamed.status_code == 200, renamed.text
    categories = {t["category"] for t in client.get("/api/transactions").json()["items"]}
    assert "Kredit" in categories and "Darlehen" not in categories
    assert client.get("/api/rules/category").json()[0]["category"] == "Kredit"
    assert [b["category"] for b in client.get("/api/budgets").json()] == ["Kredit"]

    deleted = client.delete(f"/api/categories/{cat['id']}", params={"replacement": "Fees"})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"transactions_moved": 2}
    after = [t["category"] for t in client.get("/api/transactions").json()["items"] if t["amount_minor"] == -25000]
    assert after == ["Fees", "Fees"]
    assert client.get("/api/rules/category").json() == []   # its learned rule is gone
    assert client.get("/api/budgets").json() == []
    assert _custom(client) == []


def test_delete_without_replacement_sends_transactions_to_review(client):
    tx = _setup(client)
    cat = client.post("/api/categories", json={"name": "Schulden"}).json()
    client.patch(f"/api/transactions/{tx[-300]['id']}", json={"category": "Schulden"})
    client.delete(f"/api/categories/{cat['id']}")
    kiosk = next(t for t in client.get("/api/transactions").json()["items"] if t["amount_minor"] == -300)
    assert kiosk["category"] == "Other Expense" and kiosk["needs_review"]


def test_names_are_checked(client):
    assert client.post("/api/categories", json={"name": "Darlehen"}).status_code == 200
    assert client.post("/api/categories", json={"name": "darlehen"}).status_code == 409   # case-insensitive
    assert client.post("/api/categories", json={"name": "groceries"}).status_code == 409   # built-in
    assert client.post("/api/categories", json={"name": "   "}).status_code == 422
    assert client.post("/api/categories", json={"name": "x" * 41}).status_code == 422
    german = client.post("/api/categories", json={"name": "Groceries"}, headers={"Accept-Language": "de"})
    assert german.json()["detail"] == "„Groceries“ ist eine eingebaute Kategorie."
    other = client.post("/api/categories", json={"name": "Schulden"}).json()
    assert client.delete(f"/api/categories/{other['id']}", params={"replacement": "Nope"}).status_code == 422
    assert client.delete("/api/categories/99999").status_code == 404
