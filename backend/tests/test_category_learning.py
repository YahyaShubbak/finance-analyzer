"""Assigning a category by hand teaches the app: similar existing
transactions and future imports get the same category; hand-made
corrections are never overwritten; a learned rule can be forgotten."""
from __future__ import annotations

import io

import pytest

from app.db.models import CategoryRule
from app.normalization.category import categorize
from app.services.rule_service import derive_category_pattern


@pytest.mark.parametrize(("text", "expected"), [
    ("Lastschrift / Belastung REWE Markt GmbH Einkauf 12,34 EUR vom 01.09.", "REWE Markt GmbH"),
    ("Dauerauftrag Max Mustermann Miete September", "Max Mustermann Miete"),
    ("Gutschrift / Ueberweisung Arbeitgeber AG Gehalt September", "Arbeitgeber AG Gehalt"),
    ("SEPA-Überweisung an Erika Musterfrau EREF+000123 Geschenk", "Erika Musterfrau"),
    ("Kino Palast", "Kino Palast"),
    ("BAECKEREI BEISPIEL BERLIN", "BAECKEREI BEISPIEL BERLIN"),
    ("Stadtwerke Beispielstadt Abschlag 2026/09 Kd-Nr 4711", "Stadtwerke Beispielstadt Abschlag"),
])
def test_pattern_names_the_payee(text, expected):
    pattern = derive_category_pattern(text)
    assert pattern == expected
    assert pattern in text  # always matches the transaction it was learned from


@pytest.mark.parametrize("text", [
    "PayPal Europe S.a.r.l. et Cie S.C.A",
    "PayPal",
    "Lastschrift EREF+123456 MREF+AB12",
    "Kartenzahlung",
])
def test_nothing_is_learned_without_an_identifying_payee(text):
    assert derive_category_pattern(text) is None


def _rule(id, pattern, category):
    return CategoryRule(id=id, pattern=pattern, is_regex=False, match_field="merchant", category=category,
                        priority=0, is_user_defined=True)


def test_more_specific_lesson_wins_and_whole_words_only():
    rules = [_rule(1, "REWE", "Groceries"), _rule(2, "REWE Getränke", "Drinks")]
    assert categorize("REWE Getränke Markt", None, -500, rules) == "Drinks"
    assert categorize("REWE Markt", None, -500, rules) == "Groceries"
    assert categorize("Brewery Hofladen", None, -500, rules) == "Other Expense"  # "rewe" inside a word


# --- through the API ------------------------------------------------------------

def _account(client):
    return client.post("/api/accounts", json={"name": "Giro", "account_type": "checking"}).json()["id"]


def _import(client, account_id, rows: list[str], name: str):
    content = ("Date,Description,Amount\n" + "\n".join(rows) + "\n").encode()
    files = {"file": (name, io.BytesIO(content), "text/csv")}
    preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id}).json()
    commit = client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": account_id})
    assert commit.status_code == 200, commit.text


def _by_amount(client):
    return {t["amount_minor"]: t for t in client.get("/api/transactions", params={"page_size": 100}).json()["items"]}


def test_learning_applies_to_similar_and_future_transactions_but_not_to_manual_ones(client):
    account_id = _account(client)
    _import(client, account_id, [
        "2026-03-01,Kartenzahlung Kiosk Sonnenschein Einkauf 4.50 EUR vom 28.02.,-4.50",
        "2026-03-05,Kartenzahlung Kiosk Sonnenschein Einkauf 7.20 EUR vom 04.03.,-7.20",
        "2026-03-06,Kiosk Sonnenscheinweg Getraenke,-3.00",
        "2026-03-07,Kartenzahlung Kiosk Sonnenschein Einkauf 2.00 EUR vom 06.03.,-2.00",
    ], "march.csv")
    tx = _by_amount(client)
    assert tx[-450]["category"] == "Other Expense" and tx[-450]["needs_review"]
    # corrected by hand before anything was learned
    client.patch(f"/api/transactions/{tx[-200]['id']}", json={"category": "Entertainment"})

    r = client.post(f"/api/transactions/{tx[-450]['id']}/category-rule", json={"category": "Food"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category_rule"]["pattern"] == "Kiosk Sonnenschein"
    assert body["applied_to"] == 1

    tx = _by_amount(client)
    assert tx[-450]["category"] == "Food" and not tx[-450]["needs_review"]
    assert tx[-720]["category"] == "Food" and not tx[-720]["needs_review"]   # similar -> learned
    assert tx[-300]["category"] == "Other Expense"                          # "Sonnenscheinweg": another payee
    assert tx[-200]["category"] == "Entertainment"                          # hand-made correction kept

    _import(client, account_id, ["2026-04-02,Kartenzahlung Kiosk Sonnenschein Einkauf 9.90 EUR vom 01.04.,-9.90"],
            "april.csv")
    assert _by_amount(client)[-990]["category"] == "Food"                    # future import

    learned = client.get("/api/rules/category").json()
    assert [(r["pattern"], r["category"], r["matching_transactions"]) for r in learned] == [
        ("Kiosk Sonnenschein", "Food", 4),
    ]


def test_teaching_again_replaces_the_lesson(client):
    account_id = _account(client)
    _import(client, account_id, [
        "2026-03-01,Kiosk Sonnenschein,-4.50",
        "2026-03-05,Kiosk Sonnenschein,-7.20",
    ], "march.csv")
    tx = _by_amount(client)
    first = client.post(f"/api/transactions/{tx[-450]['id']}/category-rule", json={"category": "Food"}).json()
    second = client.post(f"/api/transactions/{tx[-450]['id']}/category-rule", json={"category": "Shopping"}).json()
    assert first["category_rule"]["id"] == second["category_rule"]["id"]
    assert second["applied_to"] == 1
    assert _by_amount(client)[-720]["category"] == "Shopping"
    assert len(client.get("/api/rules/category").json()) == 1


def test_forgetting_a_rule_reverts_only_what_it_categorized(client):
    account_id = _account(client)
    _import(client, account_id, [
        "2026-03-01,Kiosk Sonnenschein,-4.50",
        "2026-03-05,Kiosk Sonnenschein,-7.20",
    ], "march.csv")
    tx = _by_amount(client)
    rule_id = client.post(f"/api/transactions/{tx[-450]['id']}/category-rule",
                          json={"category": "Food"}).json()["category_rule"]["id"]

    r = client.delete(f"/api/rules/category/{rule_id}")
    assert r.status_code == 200, r.text
    assert r.json()["transactions_changed"] == 1
    tx = _by_amount(client)
    assert tx[-720]["category"] == "Other Expense" and tx[-720]["needs_review"]
    assert tx[-450]["category"] == "Food"  # assigned by hand, stays
    assert client.get("/api/rules/category").json() == []
    assert client.delete(f"/api/rules/category/{rule_id}").status_code == 404


def test_builtin_rules_cannot_be_forgotten(client):
    client.get("/api/rules/category")
    from sqlmodel import Session, select

    import app.db.session as db_session
    from app.services.duplicate_preview_service import load_rules

    with Session(db_session.engine) as session:
        load_rules(session)  # creates the built-in rules
        builtin = session.exec(select(CategoryRule).where(CategoryRule.is_user_defined == False)).first()  # noqa: E712
    assert client.delete(f"/api/rules/category/{builtin.id}").status_code == 404


def test_empty_category_is_rejected(client):
    account_id = _account(client)
    _import(client, account_id, ["2026-03-01,Kiosk Sonnenschein,-4.50"], "march.csv")
    tx = _by_amount(client)
    assert client.post(f"/api/transactions/{tx[-450]['id']}/category-rule", json={"category": ""}).status_code == 422


def test_payment_without_identifying_payee_changes_only_itself(client):
    """All PayPal lines without a named merchant look alike — teaching one
    of them must not give every PayPal payment the same category."""
    account_id = _account(client)
    _import(client, account_id, [
        "2026-03-01,PayPal Europe S.a.r.l. et Cie S.C.A,-4.50",
        "2026-03-05,PayPal Europe S.a.r.l. et Cie S.C.A,-7.20",
    ], "march.csv")
    tx = _by_amount(client)
    r = client.post(f"/api/transactions/{tx[-450]['id']}/category-rule", json={"category": "Shopping"})
    assert r.status_code == 200, r.text
    assert r.json()["category_rule"] is None and r.json()["applied_to"] == 0
    tx = _by_amount(client)
    assert tx[-450]["category"] == "Shopping"
    assert tx[-720]["category"] != "Shopping"
    assert client.get("/api/rules/category").json() == []
