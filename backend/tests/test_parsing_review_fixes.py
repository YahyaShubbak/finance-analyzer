"""Regression tests from the second review of the import parsers: every
case here produced a wrong amount, sign, date or currency before."""
from __future__ import annotations

import io

import pytest
from openpyxl import Workbook
from sqlmodel import select

from app.db.models import Account, AccountType, Transaction
from app.importers.column_detection import detect_columns
from app.importers.csv_importer import CSVImporter
from app.importers.parsing_utils import AmountParseError, parse_amount_to_decimal
from app.importers.pdf_importer import PDFImporter
from app.importers.xlsx_importer import XLSXImporter
from app.services.duplicate_preview_service import classify_import_rows
from app.services.import_service import commit_parsed_import
from tests.pdf_fixtures import write_text_pdf


def _pdf(tmp_path, lines, name="s.pdf"):
    return PDFImporter(write_text_pdf(tmp_path / name, lines)).parse()


def _csv(tmp_path, content, name="x.csv", encoding="utf-8"):
    path = tmp_path / name
    path.write_bytes(content.encode(encoding))
    return CSVImporter(path).parse()


def _amounts(result):
    return [t.parsed_amount_minor for t in result.transactions]


# --- PDF ----------------------------------------------------------------------

def test_card_markers_keep_their_direction(tmp_path):
    """CR/DR and S/H already state the direction; the card statement's
    sign inversion must only apply to plain numbers."""
    result = _pdf(tmp_path, [
        "Credit Card Statement", "Statement period: 01.09.2026 - 30.09.2026",
        "03.09.2026 TESCO STORES 45.00",
        "10.09.2026 PAYMENT RECEIVED THANK YOU 300.00 CR",
        "15.09.2026 SHELL 60.00 DR",
        "18.09.2026 REFUND -20.00",
    ])
    assert _amounts(result) == [-4500, 30000, -6000, 2000]

    german = _pdf(tmp_path, [
        "Kreditkartenabrechnung", "Abrechnungszeitraum: 01.09.2026 - 30.09.2026",
        "03.09. REWE 45,00 S", "10.09. Zahlung erhalten 300,00 H",
    ], name="de.pdf")
    assert _amounts(german) == [-4500, 30000]


def test_year_comes_from_the_statement_not_from_today(tmp_path):
    result = _pdf(tmp_path, [
        "Kontoauszug Nummer 003 / 2025 vom 01.03.2025 bis 31.03.2025",
        "03.03. 03.03. Lastschrift REWE -45,00",
    ])
    assert result.period_start == "2025-03-01"
    assert result.transactions[0].parsed_date == "2025-03-03"


def test_yearless_dates_without_any_year_are_reported(tmp_path):
    result = _pdf(tmp_path, ["Kontoauszug", "03.03. 03.03. Lastschrift REWE -45,00", "04.03. Miete -900,00"])
    assert all(t.parsed_date is None for t in result.transactions)
    assert any("without a year" in i.message for i in result.issues)


def test_balance_lines_are_not_transactions(tmp_path):
    result = _pdf(tmp_path, [
        "Kontoauszug", "Zeitraum: 01.09.2026 - 30.09.2026",
        "01.09.2026 Alter Kontostand 1.000,00",
        "03.09.2026 Lastschrift REWE -45,00",
        "30.09.2026 Neuer Kontostand 955,00",
    ])
    assert _amounts(result) == [-4500]
    assert any("balance line" in i.message for i in result.issues)


def test_spaced_signs_and_space_grouping(tmp_path):
    result = _pdf(tmp_path, [
        "Kontoauszug", "Zeitraum: 01.09.2026 - 30.09.2026",
        "03.09.2026 Gutschrift Erstattung + 100,00 - 50,00",
        "04.09.2026 Loyer -1 234,56",
        "05.09.2026 Lastschrift 900,00-",
    ])
    assert _amounts(result) == [10000, -123456, -90000]


def test_card_line_with_foreign_amount_books_the_card_currency_amount(tmp_path):
    result = _pdf(tmp_path, [
        "Kreditkartenabrechnung", "Abrechnungszeitraum: 01.09.2026 - 30.09.2026",
        "03.09.2026 AMAZON.COM SEATTLE USD 12,00 11,06",
        "05.09.2026 HOTEL NYC 200,00 USD 184,33",
    ])
    assert _amounts(result) == [-1106, -18433]
    assert all(t.parsed_currency is None for t in result.transactions)
    assert "USD 12,00" in result.transactions[0].original_description


def test_separate_unsigned_debit_credit_columns_are_refused(tmp_path):
    result = _pdf(tmp_path, [
        "Kontoauszug", "Zeitraum: 01.03.2025 - 31.03.2025",
        "Datum Buchungstext Belastung Gutschrift",
        "03.03.2025 Lastschrift REWE Markt 45,00",
        "15.03.2025 Gehalt Arbeitgeber AG 2.500,00",
    ])
    assert result.has_errors
    assert any("separate columns" in i.message for i in result.issues)


def test_unreadable_dated_lines_are_reported(tmp_path):
    result = _pdf(tmp_path, [
        "Kontoauszug", "Zeitraum: 01.09.2026 - 30.09.2026",
        "03.09.2026 REWE -45,00",
        "04.09.2026 Dauerauftrag Miete -900,00 EUR Ref. 2026/09",
    ])
    assert len(result.transactions) == 1
    assert any("could not be read as a transaction" in i.message for i in result.issues)


# --- CSV / XLSX ----------------------------------------------------------------

def test_volksbank_soll_haben_column_and_saldo_rows(tmp_path):
    content = (
        '"Buchungstag";"Valuta";"Zahlungsempfänger";"Vorgang/Verwendungszweck";"Währung";"Umsatz";"Soll/Haben"\n'
        '"26.09.2026";"26.09.2026";"REWE Markt";"Lastschrift Einkauf";"EUR";"42,90";"S"\n'
        '"25.09.2026";"25.09.2026";"Arbeitgeber AG";"Gehalt";"EUR";"2.500,00";"H"\n'
        '"30.09.2026";"";"Anfangssaldo";"";"EUR";"1.000,00";"H"\n'
        '"30.09.2026";"";"Endsaldo";"";"EUR";"3.457,10";"H"\n'
    )
    result = _csv(tmp_path, content, encoding="cp1252")
    assert _amounts(result) == [-4290, 250000]
    assert any("balance row" in i.message for i in result.issues)


def test_sign_indicator_column_found_by_its_values(tmp_path):
    result = _csv(tmp_path, "Datum;Text;Betrag;Kz\n01.02.2026;Kino;12,00;S\n02.02.2026;Gehalt;2500,00;H\n")
    assert _amounts(result) == [-1200, 250000]


def test_original_currency_and_foreign_amount_columns_are_never_used():
    n26 = detect_columns(["Booking Date", "Value Date", "Partner Name", "Partner Iban", "Type", "Payment Reference",
                          "Account Name", "Amount (EUR)", "Original Amount", "Original Currency", "Exchange Rate"])
    assert n26["amount"] == "Amount (EUR)" and n26["currency"] is None
    generic = detect_columns(["Buchungstag", "Verwendungszweck", "Betrag in Fremdwährung", "Betrag in EUR"])
    assert generic["amount"] == "Betrag in EUR"


def test_a_non_date_cell_does_not_break_date_format_detection(tmp_path):
    result = _csv(tmp_path, "Date,Description,Amount\n13/02/2026,A,-1.00\n03/04/2026,B,-2.00\nTotal,,-3.00\n")
    assert [t.parsed_date for t in result.transactions] == ["2026-02-13", "2026-04-03"]

    pending = _csv(tmp_path, "Date,Description,Amount\n01/02/2026,A,-1.00\n03/04/2026,B,-2.00\nPending,C,-3.00\n",
                   name="p.csv")
    assert pending.ambiguous and len(pending.date_format_candidates) == 2  # still asks d/m vs m/d


def test_pending_and_cancelled_rows_are_skipped(tmp_path):
    comdirect = _csv(tmp_path, (
        ';\n"Umsätze Girokonto";"Zeitraum: 30 Tage"\n\n'
        '"Buchungstag";"Wertstellung (Valuta)";"Vorgang";"Buchungstext";"Umsatz in EUR";\n'
        '"offen";"28.09.2026";"Kartenzahlung";"REWE";"-12,34";\n'
        '"27.09.2026";"27.09.2026";"Lastschrift";"Strom";"-80,00";\n'
    ))
    assert _amounts(comdirect) == [-8000]
    revolut = _csv(tmp_path, (
        "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"
        "CARD_PAYMENT,Current,2026-09-02 10:00:00,2026-09-02 11:00:00,Coffee,-2.50,0.00,EUR,COMPLETED,97.50\n"
        "TRANSFER,Current,2026-09-03 10:00:00,2026-09-03 10:00:00,Wire,-100.00,1.50,EUR,COMPLETED,-4.00\n"
        "CARD_PAYMENT,Current,2026-09-04 10:00:00,,Pending shop,-5.00,0.00,EUR,PENDING,\n"
    ), name="r.csv")
    assert revolut.detected_layout == "Revolut"
    assert _amounts(revolut) == [-250, -10150]  # fee charged on top; pending row skipped


def test_empty_amount_column_falls_back_to_debit_credit(tmp_path):
    result = _csv(tmp_path, "Buchungstag;Verwendungszweck;Betrag;Soll;Haben\n26.09.2026;Einkauf;;42,90;\n"
                            "25.09.2026;Gehalt;;;2500,00\n")
    assert _amounts(result) == [-4290, 250000]


def test_commerzbank_export_is_recognized(tmp_path):
    result = _csv(tmp_path, "Buchungstag;Wertstellung;Umsatzart;Buchungstext;Betrag;Währung;IBAN Kontoinhaber\n"
                            "26.09.2026;26.09.2026;Lastschrift;REWE SAGT DANKE;-42,90;EUR;DE02120300000000202051\n")
    assert result.detected_layout == "Commerzbank" and not result.ambiguous
    assert result.transactions[0].original_description == "REWE SAGT DANKE"


def test_xlsx_sub_cent_numbers_are_rejected_like_text(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Datum", "Text", "Betrag"])
    ws.append(["02.01.2026", "A", 12.345])
    path = tmp_path / "x.xlsx"
    wb.save(path)
    result = XLSXImporter(path).parse()
    assert result.transactions[0].parsed_amount_minor is None
    assert any("more than two decimal places" in i.message for i in result.issues)


@pytest.mark.parametrize("raw", ["-12,00 H", "+12,00 S", "(12,00) CR", "12 34"])
def test_contradictory_or_malformed_amounts_are_errors(raw):
    with pytest.raises(AmountParseError):
        parse_amount_to_decimal(raw)


# --- duplicates -------------------------------------------------------------------

def _dkb(rows):
    head = ('"Buchungsdatum";"Wertstellung";"Status";"Zahlungspflichtige*r";"Zahlungsempfänger*in";'
            '"Verwendungszweck";"Umsatztyp";"IBAN";"Betrag (€)"\n')
    return head + "".join(f'"{d}";"{d}";"Gebucht";"Max";"{payee}";"VISA Debitkartenumsatz";"Ausgang";"";"{a}"\n'
                          for d, payee, a in rows)


def test_exact_duplicate_requires_the_same_counterparty(session, tmp_path):
    account = Account(name="Giro", account_type=AccountType.CHECKING)
    session.add(account)
    session.commit()
    session.refresh(account)
    first = _csv(tmp_path, _dkb([("26.09.26", "REWE", "-5,00")]), name="a.csv")
    commit_parsed_import(session, first, account.id, stored_path="")

    overlap = _csv(tmp_path, _dkb([("26.09.26", "Lidl", "-5,00"), ("26.09.26", "REWE", "-5,00")]), name="b.csv")
    statuses = [c.status for c in classify_import_rows(session, account, overlap.transactions)]
    assert statuses == ["new", "exact_duplicate"]

    commit_parsed_import(session, overlap, account.id, stored_path="")
    merchants = sorted(t.merchant for t in session.exec(select(Transaction)).all())
    assert merchants == ["Lidl", "REWE"]


def test_card_csv_with_positive_purchases_is_inverted_and_says_so(client):
    card = client.post("/api/accounts", json={"name": "Amex", "account_type": "credit_card"}).json()["id"]
    csv = b"Date,Description,Amount\n2026-09-01,Shop A,12.00\n2026-09-02,Shop B,30.00\n2026-09-03,Shop C,8.50\n"
    preview = client.post("/api/imports/preview", files={"file": ("amex.csv", io.BytesIO(csv), "text/csv")},
                          data={"account_id": card}).json()
    assert [t["parsed_amount_minor"] for t in preview["transactions"]] == [-1200, -3000, -850]
    assert preview["options"]["invert_signs"] is True
    assert any("amounts were inverted" in i["message"] for i in preview["issues"])

    # the user says no: respected, no warning, nothing inverted
    kept = client.post(f"/api/imports/{preview['staging_id']}/reparse",
                       json={"account_id": card, "options": {"invert_signs": False}}).json()
    assert [t["parsed_amount_minor"] for t in kept["transactions"]] == [1200, 3000, 850]
    assert not any("inverted" in i["message"] for i in kept["issues"])

    # the commit parses exactly like the preview the user confirmed
    again = client.post(f"/api/imports/{preview['staging_id']}/reparse",
                        json={"account_id": card, "options": {}}).json()
    commit = client.post("/api/imports/commit", json={"staging_id": again["staging_id"], "account_id": card})
    assert commit.status_code == 200, commit.text
    amounts = sorted(t["amount_minor"] for t in client.get("/api/transactions").json()["items"])
    assert amounts == [-3000, -1200, -850]


def test_bank_csv_with_mostly_positive_amounts_is_not_inverted(client):
    giro = client.post("/api/accounts", json={"name": "Giro", "account_type": "checking"}).json()["id"]
    csv = b"Date,Description,Amount\n2026-09-01,Salary,2000.00\n2026-09-02,Refund,30.00\n2026-09-03,Gift,8.50\n"
    preview = client.post("/api/imports/preview", files={"file": ("giro.csv", io.BytesIO(csv), "text/csv")},
                          data={"account_id": giro}).json()
    assert [t["parsed_amount_minor"] for t in preview["transactions"]] == [200000, 3000, 850]
