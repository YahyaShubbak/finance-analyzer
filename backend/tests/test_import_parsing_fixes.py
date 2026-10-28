"""Regression tests for amount/date/column parsing — each case silently
produced wrong numbers before."""
from __future__ import annotations

from decimal import Decimal

import pytest
from openpyxl import Workbook

from app.importers.base import ParseOptions
from app.importers.column_detection import detect_columns
from app.importers.csv_importer import CSVImporter
from app.importers.currency import normalize_currency
from app.importers.parsing_utils import (
    AmbiguousAmountError,
    AmountParseError,
    DateParseError,
    detect_date_format,
    detect_decimal_separator,
    parse_amount_to_decimal,
    parse_date_flexible,
)
from app.importers.xlsx_importer import XLSXImporter


@pytest.mark.parametrize("raw,expected", [
    ("−42,90", Decimal("-42.90")),   # Unicode minus used to lose its sign
    ("– 42,90", Decimal("-42.90")),  # en dash from PDF exports
    ("42,90-", Decimal("-42.90")),        # trailing minus (common in German exports)
    ("42,90 S", Decimal("-42.90")),       # Soll
    ("42,90 H", Decimal("42.90")),        # Haben
    ("42.90 DR", Decimal("-42.90")),
    ("42.90 CR", Decimal("42.90")),
    ("EUR -1.234,56", Decimal("-1234.56")),
    ("1 234,56", Decimal("1234.56")),
    ("1'234.50", Decimal("1234.50")),
    ("1.234.567", Decimal("1234567")),
])
def test_sign_and_grouping_notations(raw, expected):
    assert parse_amount_to_decimal(raw) == expected


@pytest.mark.parametrize("raw", ["1.500", "1,234", "12.345"])
def test_ambiguous_separator_raises_instead_of_guessing(raw):
    with pytest.raises(AmbiguousAmountError):
        parse_amount_to_decimal(raw)


def test_file_level_separator_resolves_ambiguity():
    assert parse_amount_to_decimal("1.500", ",") == Decimal("1500")
    assert parse_amount_to_decimal("1,234", ".") == Decimal("1234")
    assert detect_decimal_separator(["1.500", "12,30", "-4,00"]) == ","
    assert detect_decimal_separator(["1,234.56", "3.50"]) == "."
    assert detect_decimal_separator(["1.500"]) is None


def test_garbage_amounts_rejected():
    for raw in ("12-34", "abc", "1.23.45,6"):
        with pytest.raises(AmountParseError):
            parse_amount_to_decimal(raw)


def test_date_format_decided_per_file_not_per_value():
    # 01/15 proves month/day for the whole column, so 02/03 is 3 February.
    assert detect_date_format(["01/15/2026", "02/03/2026"])[0] == "%m/%d/%Y"
    assert detect_date_format(["15/01/2026", "02/03/2026"])[0] == "%d/%m/%Y"
    fmt, candidates = detect_date_format(["01/02/2026", "03/04/2026"])
    assert fmt is None and set(candidates) == {"%d/%m/%Y", "%m/%d/%Y"}


def test_two_digit_year_not_read_as_year_25():
    assert parse_date_flexible("01.02.25").isoformat() == "2025-02-01"


def test_single_ambiguous_date_raises():
    with pytest.raises(DateParseError):
        parse_date_flexible("02/03/2026")


def test_value_date_column_never_used_as_amount():
    mapping = detect_columns(["Date", "Value Date", "Payee", "Debit", "Credit"])
    assert mapping["amount"] is None
    assert mapping["value_date"] == "Value Date"
    assert (mapping["debit"], mapping["credit"]) == ("Debit", "Credit")


def test_booking_type_not_used_as_description():
    mapping = detect_columns(["Buchungstag", "Valutadatum", "Buchungstext", "Verwendungszweck",
                              "Beguenstigter/Zahlungspflichtiger", "Betrag", "Waehrung"])
    assert mapping["date"] == "Buchungstag"
    assert mapping["description"] == "Verwendungszweck"
    assert mapping["booking_text"] == "Buchungstext"


@pytest.mark.parametrize("raw,iso", [("EUR", "EUR"), ("eur", "EUR"), ("€", "EUR"), ("Euro", "EUR"),
                                      ("£", "GBP"), ("$", None), ("XYZ", None)])
def test_currency_normalization(raw, iso):
    assert normalize_currency(raw) == iso


def _csv(tmp_path, content: str, encoding="utf-8", name="x.csv", options=None):
    path = tmp_path / name
    path.write_bytes(content.encode(encoding))
    return CSVImporter(path, options=options).parse()


def test_debit_credit_zero_filled_columns(tmp_path):
    result = _csv(tmp_path, "Datum;Beschreibung;Soll;Haben\n01.02.2026;REWE;12,00;0,00\n02.02.2026;Gehalt;0,00;2500,00\n")
    assert [t.parsed_amount_minor for t in result.transactions] == [-1200, 250000]


def test_dkb_export_with_preamble_and_payer_payee_columns(tmp_path):
    content = (
        '"Konto";"Girokonto DE02120300000000202051"\n'
        '""\n'
        '"Kontostand vom 28.09.2026:";"1.234,56 €"\n'
        '""\n'
        '"Buchungsdatum";"Wertstellung";"Status";"Zahlungspflichtige*r";"Zahlungsempfänger*in";'
        '"Verwendungszweck";"Umsatztyp";"IBAN";"Betrag (€)";"Gläubiger-ID";"Mandatsreferenz";"Kundenreferenz"\n'
        '"26.09.26";"26.09.26";"Gebucht";"Max Mustermann";"REWE Markt GmbH";"Einkauf 1234";"Ausgang";'
        '"DE89370400440532013000";"-1.042,90";"";"";""\n'
        '"25.09.26";"25.09.26";"Gebucht";"Arbeitgeber AG";"Max Mustermann";"Gehalt September";"Eingang";'
        '"DE89370400440532013000";"2.500,00";"";"";""\n'
    )
    result = _csv(tmp_path, content)
    assert not result.ambiguous, result.issues
    assert result.detected_layout == "DKB"
    assert result.header_row_index == 4
    rewe, salary = result.transactions
    assert (rewe.parsed_date, rewe.parsed_amount_minor, rewe.counterparty) == ("2026-09-26", -104290, "REWE Markt GmbH")
    assert (salary.parsed_amount_minor, salary.counterparty) == (250000, "Arbeitgeber AG")
    assert rewe.original_description == "Einkauf 1234"
    assert rewe.counterparty_iban == "DE89370400440532013000"


def test_ing_export_duplicate_currency_headers(tmp_path):
    content = (
        "Umsatzanzeige;Datei erstellt am: 28.09.2026 10:00\n\n"
        "Buchung;Wertstellungsdatum;Auftraggeber/Empfänger;Buchungstext;Verwendungszweck;Saldo;Währung;Betrag;Währung\n"
        "26.09.2026;26.09.2026;Stadtwerke;Lastschrift;Strom September;1.000,00;EUR;-80,00;EUR\n"
    )
    result = _csv(tmp_path, content, encoding="cp1252")
    assert not result.ambiguous, result.issues
    tx = result.transactions[0]
    assert tx.parsed_amount_minor == -8000   # not the Saldo column
    assert tx.counterparty == "Stadtwerke"


def test_ambiguous_dates_ask_the_user_and_options_resolve_them(tmp_path):
    content = "Date,Description,Amount\n01/02/2026,A,-1.00\n03/04/2026,B,-2.00\n"
    first = _csv(tmp_path, content)
    assert first.ambiguous
    assert set(first.date_format_candidates) == {"%d/%m/%Y", "%m/%d/%Y"}

    resolved = _csv(tmp_path, content, options=ParseOptions(date_format="%m/%d/%Y"))
    assert not resolved.ambiguous
    assert [t.parsed_date for t in resolved.transactions] == ["2026-01-02", "2026-03-04"]


def test_ambiguous_thousands_separator_asks_the_user(tmp_path):
    content = "Datum;Text;Betrag\n01.02.2026;Miete;-1.500\n02.02.2026;Bonus;2.000\n"
    first = _csv(tmp_path, content)
    assert first.ambiguous and first.needs_decimal_separator

    resolved = _csv(tmp_path, content, options=ParseOptions(decimal_separator=","))
    assert [t.parsed_amount_minor for t in resolved.transactions] == [-150000, 200000]


def test_manual_column_mapping(tmp_path):
    content = "When;What;How much\n01.02.2026;Kino;-12,00\n"
    assert _csv(tmp_path, content).ambiguous
    options = ParseOptions(column_mapping={"date": "When", "description": "What", "amount": "How much"})
    result = _csv(tmp_path, content, options=options)
    assert not result.ambiguous
    assert result.transactions[0].parsed_amount_minor == -1200


def test_footer_lines_ignored_with_notice(tmp_path):
    content = "Datum;Text;Betrag\n01.02.2026;Kino;-12,00\n;Kontostand;\n"
    result = _csv(tmp_path, content)
    assert len(result.transactions) == 1
    assert any("ignored" in i.message for i in result.issues)


def test_unknown_currency_warns_and_is_not_stored(tmp_path):
    result = _csv(tmp_path, "Date,Description,Amount,Currency\n2026-02-01,X,-1.00,€\n2026-02-02,Y,-1.00,Dollars\n")
    assert [t.parsed_currency for t in result.transactions] == ["EUR", None]
    assert any("Unknown currency 'Dollars'" in i.message for i in result.issues)


def test_xlsx_negative_debit_is_still_an_expense(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Datum", "Beschreibung", "Soll", "Haben"])
    ws.append(["01.02.2026", "REWE", -45.0, None])
    ws.append(["02.02.2026", "Lidl", 12.5, 0])
    path = tmp_path / "x.xlsx"
    wb.save(path)

    result = XLSXImporter(path).parse()
    assert [t.parsed_amount_minor for t in result.transactions] == [-4500, -1250]
