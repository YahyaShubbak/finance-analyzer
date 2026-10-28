"""Findings of an independent accounting audit, as regression tests. Invented data."""
from __future__ import annotations

import io

from tests.pdf_fixtures import write_text_pdf


def _account(client, name, account_type="credit_card", iban=None):
    body = {"name": name, "account_type": account_type}
    if iban:
        body["iban"] = iban
    return client.post("/api/accounts", json=body).json()["id"]


def _import(client, account, name, content, kind="text/csv", decisions=None):
    preview = client.post("/api/imports/preview", data={"account_id": account},
                          files={"file": (name, io.BytesIO(content), kind)}).json()
    body = {"staging_id": preview["staging_id"], "account_id": account}
    if decisions:
        body["row_decisions"] = [{"source_row_index": r["source_row_index"], "decision": decisions}
                                 for r in preview["transactions"]]
    r = client.post("/api/imports/commit", json=body)
    assert r.status_code == 200, r.text
    return preview, r.json()


def _statement(tmp_path, name, period, lines, total):
    return write_text_pdf(tmp_path / name, ["Credit Card Statement", "VISA ending 1234", f"Statement Period: {period}",
                                            *lines, f"Statement Total: {total} EUR"]).read_bytes()


def _expenses(client):
    return client.get("/api/analytics/totals").json()["expenses_minor"]


MARCH = ["02.03.2026 Buchladen Beispiel 40.00 EUR", "30.03.2026 Kiosk Muster 4.00 EUR", "31.03.2026 Kiosk Muster 4.00 EUR"]
EXPORT_APRIL = (b"Datum,Beschreibung,Betrag\n2026-04-01,Kiosk Muster,-4.00\n2026-04-02,Kiosk Muster,-4.00\n"
                b"2026-04-20,Fahrradladen Beispiel,-25.00\n")


def test_repeat_purchases_in_files_of_different_periods_are_all_counted(client, tmp_path):
    card = _account(client, "Karte")
    _import(client, card, "m.pdf", _statement(tmp_path, "m.pdf", "01.03.2026 - 31.03.2026", MARCH, "48.00"), "application/pdf")
    _import(client, card, "april.csv", EXPORT_APRIL)
    assert _expenses(client) == 4800 + 3300


def test_repeat_purchases_counted_in_the_other_order_too(client, tmp_path):
    card = _account(client, "Karte")
    _import(client, card, "april.csv", EXPORT_APRIL)
    _import(client, card, "m.pdf", _statement(tmp_path, "m.pdf", "01.03.2026 - 31.03.2026", MARCH, "48.00"), "application/pdf")
    assert _expenses(client) == 4800 + 3300


def test_identical_purchases_on_consecutive_statements_are_two(client, tmp_path):
    """A 4.00 ticket on 31.03 in March, another one on 31.03 booked in April
    (listed with its purchase date on the April statement)."""
    card = _account(client, "Karte")
    _import(client, card, "mar.pdf", _statement(tmp_path, "mar.pdf", "01.03.2026 - 31.03.2026",
                                                ["10.03.2026 Buchladen Beispiel 40.00 EUR", "31.03.2026 Kiosk Muster 4.00 EUR"],
                                                "44.00"), "application/pdf")
    _import(client, card, "apr.pdf", _statement(tmp_path, "apr.pdf", "01.04.2026 - 30.04.2026",
                                                ["31.03.2026 Kiosk Muster 4.00 EUR", "15.04.2026 Fahrradladen Beispiel 25.00 EUR"],
                                                "29.00"), "application/pdf")
    assert _expenses(client) == 7300


def test_a_restore_keeps_the_users_keep_decisions(client, tmp_path):
    card = _account(client, "Karte")
    # the same purchases in the statement and the export, which the user says are separate ones
    _import(client, card, "m.pdf", _statement(tmp_path, "m.pdf", "01.03.2026 - 31.03.2026", MARCH, "48.00"), "application/pdf")
    export_march = b"Datum,Beschreibung,Betrag\n2026-03-31,Kiosk Muster,-4.00\n"
    preview, _commit = _import(client, card, "march.csv", export_march, decisions="keep")
    assert preview["exact_duplicate_count"] + preview["possible_duplicate_count"] == 1
    assert _expenses(client) == 5200
    name = client.post("/api/backup/create").json()["filename"]
    assert client.post(f"/api/backup/{name}/restore", data={"confirm": "true"}).status_code == 200
    assert _expenses(client) == 5200


def test_a_statement_counts_its_bookings_kept_from_the_export(client, tmp_path, monkeypatch):
    """Merged after an older version imported both: the export's copy is kept,
    the statement still adds up."""
    from app.config import settings
    from app.db.session import session_scope
    from app.services import duplicate_preview_service
    from app.services.twin_merge import TWINS_MARKER, merge_cross_file_twins

    card = _account(client, "Karte")
    export = b"Datum,Beschreibung,Betrag\n2026-03-03,Buchladen Beispiel,-40.00\n2026-03-06,Kiosk Muster,-12.00\n"
    with monkeypatch.context() as old_version:
        old_version.setattr(duplicate_preview_service, "_twin_from_other_file", lambda *a, **k: None)
        _import(client, card, "export.csv", export)
        _import(client, card, "m.pdf", _statement(tmp_path, "m.pdf", "01.03.2026 - 31.03.2026",
                                                  ["02.03.2026 Buchladen Beispiel 40.00 EUR",
                                                   "05.03.2026 Kiosk Muster 12.00 EUR"], "52.00"), "application/pdf")
    (settings.data_dir / TWINS_MARKER).unlink(missing_ok=True)
    with session_scope() as session:
        assert merge_cross_file_twins(session) == 2
    assert _expenses(client) == 5200
    [statement] = client.get(f"/api/credit-cards/{card}/statements").json()
    detail = client.get(f"/api/reconciliation/statements/{statement['id']}").json()
    assert detail["transaction_total_minor"] == 5200 and detail["diff_transactions_vs_statement_minor"] == 0


import pytest  # noqa: E402

JAN = ("01.01.2026 - 31.01.2026", ["05.01.2026 Streamingdienst Beispiel 9.99 EUR"], "9.99")
FEB = ("01.02.2026 - 28.02.2026", ["05.02.2026 Streamingdienst Beispiel 9.99 EUR"], "9.99")
GIRO_BILLS = (b"Datum,Beschreibung,Betrag\n2026-01-02,Gehalt Beispiel,1000.00\n"
              b"2026-02-24,Visa Kreditkartenabrechnung,-9.99\n2026-03-24,Visa Kreditkartenabrechnung,-9.99\n")


@pytest.mark.parametrize("order", [("giro", "jan", "feb"), ("giro", "feb", "jan"), ("feb", "jan", "giro"),
                                   ("jan", "feb", "giro"), ("feb", "giro", "jan")])
def test_equal_bills_in_a_row_are_linked_in_any_order(client, tmp_path, order):
    card, giro = _account(client, "Karte"), _account(client, "Giro", "checking")
    files = {"jan": (card, "jan.pdf", _statement(tmp_path, "jan.pdf", *JAN), "application/pdf"),
             "feb": (card, "feb.pdf", _statement(tmp_path, "feb.pdf", *FEB), "application/pdf"),
             "giro": (giro, "giro.csv", GIRO_BILLS, "text/csv")}
    for name in order:
        _import(client, *files[name])
    statuses = [s["reconciliation_status"] for s in client.get(f"/api/credit-cards/{card}/statements").json()]
    assert statuses == ["reconciled", "reconciled"]
    assert _expenses(client) == 1998  # the purchases; both debits pay the card


def test_removing_the_statement_keeps_the_bill_paid_by_the_export(client, tmp_path):
    card, giro = _account(client, "Karte"), _account(client, "Giro", "checking")
    _import(client, card, "export.csv", b"Date,Description,Amount\n2026-03-02,Restaurant Beispiel,-100.00\n"
                                        b"2026-04-21,Payment received thank you,100.00\n")
    _import(client, giro, "giro.csv", b"Date,Description,Amount\n2026-03-01,Gehalt,1000.00\n"
                                      b"2026-04-20,Visa Kreditkartenabrechnung,-100.00\n")
    _p, commit = _import(client, card, "m.pdf", _statement(tmp_path, "m.pdf", "01.03.2026 - 31.03.2026",
                                                           ["02.03.2026 Restaurant Beispiel 100.00 EUR"], "100.00"),
                         "application/pdf")
    assert _expenses(client) == 10000
    assert client.delete(f"/api/imports/{commit['import_id']}").status_code == 200
    assert _expenses(client) == 10000  # the debit is paired with the export's payment line again


def test_removing_the_export_leaves_the_real_statement_with_its_bill(client, tmp_path):
    card, giro = _account(client, "Karte"), _account(client, "Giro", "checking")
    _p, export = _import(client, card, "export.csv", b"Datum,Beschreibung,Betrag\n2026-03-03,Buchladen Beispiel,-60.00\n"
                                                     b"2026-03-11,Kiosk Muster,-40.00\n")
    _import(client, giro, "giro.csv", b"Datum,Beschreibung,Betrag\n2026-04-14,Visa Kreditkartenabrechnung,-100.00\n")
    _import(client, card, "m.pdf", _statement(tmp_path, "m.pdf", "01.03.2026 - 31.03.2026",
                                              ["02.03.2026 Buchladen Beispiel 60.00 EUR",
                                               "10.03.2026 Kiosk Muster 40.00 EUR"], "100.00"), "application/pdf")
    statements = client.get(f"/api/credit-cards/{card}/statements").json()
    assert [s["reconciliation_status"] for s in statements] == ["reconciled"]  # no second, derived one
    assert _expenses(client) == 10000
    assert client.delete(f"/api/imports/{export['import_id']}").status_code == 200
    assert [s["reconciliation_status"] for s in client.get(f"/api/credit-cards/{card}/statements").json()] == ["reconciled"]
    assert _expenses(client) == 10000


def test_a_card_payment_is_one_transfer_in_the_summary(client, tmp_path):
    """The bank's debit settles the March statement; the April statement lists
    the same money arriving ("payment received") — one movement, not two."""
    card, giro = _account(client, "Karte"), _account(client, "Giro", "checking")
    _import(client, giro, "giro.csv", b"Datum,Beschreibung,Betrag\n2026-04-10,Visa Kreditkartenabrechnung,-100.00\n")
    _import(client, card, "mar.pdf", _statement(tmp_path, "mar.pdf", "01.03.2026 - 31.03.2026",
                                                ["02.03.2026 Restaurant Beispiel 100.00 EUR"], "100.00"), "application/pdf")
    _import(client, card, "apr.pdf", _statement(tmp_path, "apr.pdf", "01.04.2026 - 30.04.2026",
                                                ["12.04.2026 PAYMENT RECEIVED THANK YOU -100.00 EUR",
                                                 "15.04.2026 Kiosk Muster 30.00 EUR"], "30.00"), "application/pdf")
    summary = client.get("/api/analytics/transfers-summary").json()
    assert (summary["total_transferred_minor"], summary["transfer_count"]) == (10000, 1)
    assert _expenses(client) == 13000
