"""Regressions for defects found by independent testers. Invented data only."""
from __future__ import annotations

import io

import pytest

from app.importers.pdf_layouts.generic_credit_card import _is_credit_marker
from app.importers.tabular import _is_balance_label
from app.normalization.merchant import normalize_merchant


@pytest.mark.parametrize("line, marked", [
    ("GUTSCHRIFT", True),
    ("Haben 12,34", True),
    ("4711 0815 GUTSCHRIFT", True),
    ("Kundenreferenz 12-345 GUTSCHRIFT", True),
    ("Haben Sie Fragen zu Ihrer Abrechnung?", False),
    ("Ihr Kreditrahmen (credit limit) beträgt 5.000 EUR", False),
    ("Diese Zahlung werden wir gutgeschrieben haben.", False),
])
def test_credit_marker_is_a_marker_not_a_sentence(line, marked):
    assert _is_credit_marker(line) is marked


@pytest.mark.parametrize("text, balance", [
    ("Anfangssaldo", True),
    ("Kontostand am 31.03.2026", True),
    ("Closing balance", True),
    ("Saldo vom 01.03.2026 1.234,56 EUR", True),
    ("Saldo der Abschlussposten", False),
    ("Kontostand-Benachrichtigung SMS", False),
])
def test_only_a_bare_balance_label_is_a_balance_row(text, balance):
    assert _is_balance_label(text) is balance


def test_learned_merchant_rules_match_whole_words():
    from app.db.models import MerchantRule

    rules = [MerchantRule(id=1, pattern="Rewe", is_regex=False, normalized_merchant="REWE Markt", is_user_defined=True)]
    assert normalize_merchant("REWE Bremen Filiale", rules) == "REWE Markt"
    assert normalize_merchant("Brewery Berlin", rules) != "REWE Markt"
    assert normalize_merchant("Andrewes Buchladen", rules) != "REWE Markt"


def _account(client, name, account_type="checking", iban=None):
    body = {"name": name, "account_type": account_type}
    if iban:
        body["iban"] = iban
    return client.post("/api/accounts", json=body)


def test_accounts_need_a_name_and_their_own_iban(client):
    giro = _account(client, "Giro", iban="DE89370400440532013000").json()["id"]
    assert client.patch(f"/api/accounts/{giro}", json={"name": "   "}).status_code == 422
    assert _account(client, "Zweites", iban="DE89 3704 0044 0532 0130 00").status_code == 409
    other = _account(client, "Tagesgeld", "savings").json()["id"]
    assert client.patch(f"/api/accounts/{other}", json={"iban": "DE89370400440532013000"}).status_code == 409


def test_an_already_imported_file_is_refused_in_the_preview(client):
    giro = _account(client, "Giro").json()["id"]
    content = b"Date,Description,Amount\n2026-03-02,Baeckerei Muster,-3.20\n"
    files = lambda: {"file": ("a.csv", io.BytesIO(content), "text/csv")}  # noqa: E731
    first = client.post("/api/imports/preview", files=files(), data={"account_id": giro}).json()
    assert client.post("/api/imports/commit", json={"staging_id": first["staging_id"], "account_id": giro}).status_code == 200
    again = client.post("/api/imports/preview", files=files()).json()
    assert again["has_errors"] and not again["auto_import"]
    assert any("already been imported" in i["message"] for i in again["issues"])


def test_a_broken_pdf_is_reported_not_a_server_error(client):
    _account(client, "Giro")
    r = client.post("/api/imports/preview", files={"file": ("kaputt.pdf", io.BytesIO(b"%PDF-1.4 broken"), "application/pdf")})
    assert r.status_code < 500, r.text


@pytest.mark.parametrize("name, expected", [
    ("....csv", "upload.csv"),
    ("a" * 300 + ".pdf", "a" * 110 + ".pdf"),
    ("../../März (1).pdf", "M_rz_1.pdf"),
])
def test_staged_file_names_keep_their_extension(name, expected):
    from app.services.import_staging import sanitize_filename

    assert sanitize_filename(name) == expected


def test_numbers_too_large_to_store_are_a_client_error(client):
    assert client.get("/api/transactions", params={"account_id": 2**63}).status_code == 422
    assert client.patch(f"/api/transactions/{2**63}", json={"category": "Food"}).status_code in (404, 422)


def test_out_of_range_dates_and_amounts_are_unreadable_rows(client):
    giro = _account(client, "Giro").json()["id"]
    content = b"Date,Description,Amount\n9999-12-31,Zukunft,-5.00\n2026-03-02,Baeckerei,-99999999999999999999.00\n2026-03-03,Kiosk,-1.00\n"
    preview = client.post("/api/imports/preview", files={"file": ("x.csv", io.BytesIO(content), "text/csv")},
                          data={"account_id": giro}).json()
    assert preview["unusable_row_count"] == 2
    r = client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": giro})
    assert r.status_code == 200 and r.json()["transactions_created"] == 1


def test_search_ignores_umlaut_spelling_and_case(client):
    giro = _account(client, "Giro").json()["id"]
    content = b"Date,Description,Amount\n2026-03-02,Baeckerei Muster,-3.20\n2026-03-03,Kiosk,-1.00\n"
    preview = client.post("/api/imports/preview", files={"file": ("s.csv", io.BytesIO(content), "text/csv")},
                          data={"account_id": giro}).json()
    client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": giro})
    for term in ("BÄCKEREI", "bäckerei", "Baeckerei", "muster"):
        items = client.get("/api/transactions", params={"search": term}).json()["items"]
        assert [t["normalized_description"] for t in items] == ["Baeckerei Muster"], term
    assert client.get("/api/transactions", params={"search": "50%"}).json()["total"] == 0


def test_search_finds_umlauts_typed_without_them(client):
    giro = _account(client, "Giro").json()["id"]
    content = "Date,Description,Amount\n2026-03-02,Müller Café,-3.20\n2026-03-03,Kiosk,-1.00\n".encode()
    preview = client.post("/api/imports/preview", files={"file": ("u.csv", io.BytesIO(content), "text/csv")},
                          data={"account_id": giro}).json()
    client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": giro})
    for term in ("Muller", "mueller", "MÜLLER", "cafe", "Café"):
        items = client.get("/api/transactions", params={"search": term}).json()["items"]
        assert len(items) == 1 and items[0]["amount_minor"] == -320, term


def _csv_import(client, account_id, name, content: bytes):
    preview = client.post("/api/imports/preview", files={"file": (name, io.BytesIO(content), "text/csv")},
                          data={"account_id": account_id}).json()
    r = client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": account_id})
    assert r.status_code == 200, r.text
    return preview


def test_the_file_name_is_kept_as_the_user_knows_it(client):
    giro = _account(client, "Giro").json()["id"]
    _csv_import(client, giro, "März (1).csv", b"Date,Description,Amount\n2026-03-02,Kiosk,-1.00\n")
    assert [i["filename"] for i in client.get("/api/imports").json()] == ["März (1).csv"]


def test_a_category_with_more_refunds_than_spending_still_adds_up(client):
    giro = _account(client, "Giro").json()["id"]
    _csv_import(client, giro, "r.csv", b"Date,Description,Amount\n"
                b"2026-03-02,REWE Markt,-10.00\n2026-03-05,Netflix,-12.99\n")
    tx = {t["amount_minor"]: t for t in client.get("/api/transactions").json()["items"]}
    # a refund larger than the month's grocery spending (typed as expense: it reduces spending)
    _csv_import(client, giro, "s.csv", b"Date,Description,Amount\n2026-03-20,REWE Markt Erstattung,25.00\n")
    refund = next(t for t in client.get("/api/transactions").json()["items"] if t["amount_minor"] == 2500)
    client.patch(f"/api/transactions/{refund['id']}", json={"transaction_type": "expense", "category": tx[-1000]["category"]})
    totals = client.get("/api/analytics/totals").json()["expenses_minor"]
    rows = client.get("/api/analytics/by-category").json()
    assert sum(r["amount_minor"] for r in rows) == totals
    assert any(r["amount_minor"] < 0 for r in rows)


def test_budget_currency_is_validated(client):
    r = client.put("/api/budgets/Food", json={"amount_minor": 1000, "currency": "EURO"})
    assert r.status_code == 422


def test_an_own_accounts_iban_in_the_booking_text_links_a_transfer(client):
    """comdirect prints the counterparty IBAN only in the booking text."""
    giro = _account(client, "Giro", iban="DE89370400440532013000").json()["id"]
    savings = _account(client, "Tagesgeld", "savings", iban="DE02120300000000202051").json()["id"]
    _csv_import(client, giro, "g.csv", b"Date,Description,Amount\n"
                b"2026-03-02,Uebertrag auf DE02 1203 0000 0000 2020 51 Sparen,-500.00\n")
    _csv_import(client, savings, "t.csv", b"Date,Description,Amount\n2026-03-06,Eingang Sparen,500.00\n")
    debit = client.get("/api/transactions", params={"account_id": giro}).json()["items"][0]
    assert debit["transaction_type"] == "transfer"  # 4 days apart (beyond 3): linked by the IBAN


def test_review_queue_suggests_a_category_from_similar_sorted_transactions(client):
    giro = _account(client, "Giro").json()["id"]
    _csv_import(client, giro, "a.csv", b"Date,Description,Amount\n"
                b"2026-03-01,Sporthaus Runners Point,-80.00\n2026-03-02,Runners Point Filiale,-40.00\n"
                b"2026-03-03,Laufschuhe Runner Beispiel,-25.00\n2026-03-08,Sport Runner Muster,-35.00\n"
                b"2026-03-04,REWE Markt,-10.00\n2026-03-05,Lidl,-8.00\n"
                b"2026-03-06,ALDI Sued,-12.00\n2026-03-07,TRAILRUNNER SHOP,-60.00\n")
    items = client.get("/api/transactions", params={"needs_review": True}).json()["items"]
    unsorted = {t["normalized_description"]: t for t in items}
    assert unsorted["TRAILRUNNER SHOP"]["suggested_category"] == "Shopping"
    assert unsorted["TRAILRUNNER SHOP"]["category"] == "Other Expense"  # only suggested, not set


def test_a_merchant_name_rule_also_renames_similar_existing_transactions(client):
    giro = _account(client, "Giro").json()["id"]
    _csv_import(client, giro, "p.csv", b"Date,Description,Amount\n"
                b"2026-08-01,POSTSHOP 2KD666,-0.95\n2026-08-05,POSTSHOP 2KD666,-1.60\n2026-08-06,Baeckerei,-2.00\n")
    first = next(t for t in client.get("/api/transactions").json()["items"] if t["amount_minor"] == -95)
    r = client.post(f"/api/transactions/{first['id']}/merchant-rule", json={"normalized_merchant": "Deutsche Post"})
    assert r.status_code == 200, r.text
    assert r.json()["applied_to"] == 1
    merchants = {t["amount_minor"]: t["merchant"] for t in client.get("/api/transactions").json()["items"]}
    assert merchants[-95] == merchants[-160] == "Deutsche Post" and merchants[-200] != "Deutsche Post"
