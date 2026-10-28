"""Card accounts with their own IBAN, as found in real statements, rebuilt
from their STRUCTURE with invented content (no real data):

* an account-style PDF ("Kontoauszug") that prints money in and money out
  in two unsigned columns headed "Zahlungseingang" / "Zahlungsausgang"
  (each heading wrapped onto two lines);
* the issuer's spreadsheet export with English camel-case headers
  (TransactionDate, BookDate, ...), signed amounts, a booking type
  ("Einkauf", "Gutschrift", "Einzahlung") and the card network's merchant
  category ("GROCERY STORES/SUPERMARKETS").
"""
from __future__ import annotations

import io
from datetime import datetime

import pytest

from app.db.models import DocumentType
from app.importers.column_detection import detect_bank_format, detect_columns, normalize_header
from app.importers.pdf_importer import PDFImporter
from app.importers.xlsx_importer import XLSXImporter
from app.normalization.category import category_from_merchant_category
from tests.pdf_fixtures import write_table_pdf
from tests.xlsx_fixtures import write_xlsx

CARD_IBAN = "DE89370400440532013000"
GIRO_IBAN = "DE02120300000000202051"

IN_X, OUT_X = 440, 520  # right edges of the two amount columns


def _row(booking, value, text, amount, column):
    return [(76, booking, "l"), (143, value, "l"), (210, text, "l"), (IN_X if column == "in" else OUT_X, amount, "r")]


STATEMENT_ROWS = [
    [(71, "Kontoauszug", "l")],
    [(71, f"IBAN: {CARD_IBAN}", "l")],
    [(71, "Zeitraum: 01.09.2026 - 30.09.2026", "l"), (428, "Währung: Euro (EUR)", "l")],
    [],
    [(76, "Buchung", "l"), (143, "Valuta", "l"), (210, "Beschreibung", "l"),
     (IN_X, "Zahlungseinga", "r"), (OUT_X, "Zahlungsausga", "r")],
    [(IN_X, "ng", "r"), (OUT_X, "ng", "r")],
    _row("01.09.2026", "01.09.2026", f"Max Muster {CARD_IBAN}", "300,00", "in"),
    _row("02.09.2026", "03.09.2026", "REWE Markt Beispiel", "42,90", "out"),
    # booking-type words in a description must never be taken for column headings
    _row("04.09.2026", "04.09.2026", "Gutschrift Lastschrift Beispiel", "5,00", "out"),
    _row("05.09.2026", "06.09.2026", "Online Shop Beispiel", "19,99", "in"),
    _row("07.09.2026", "07.09.2026", "Baeckerei Beispiel & Sohn", "1.234,50", "out"),
]


def test_account_style_card_statement_reads_direction_from_the_column(tmp_path):
    result = PDFImporter(write_table_pdf(tmp_path / "card.pdf", STATEMENT_ROWS)).parse()

    assert result.document_type == DocumentType.BANK_STATEMENT
    assert not result.has_errors
    amounts = [t.parsed_amount_minor for t in result.transactions]
    assert amounts == [30000, -4290, -500, 1999, -123450]
    assert [t.parsed_date for t in result.transactions][:2] == ["2026-09-01", "2026-09-02"]
    assert result.transactions[1].extra_fields["_value_date"] == "2026-09-03"


def test_without_column_headings_nothing_is_guessed(tmp_path):
    rows = [r for r in STATEMENT_ROWS if not any(text.startswith("Zahlungs") or text == "ng" for _x, text, _a in r)]
    result = PDFImporter(write_table_pdf(tmp_path / "card.pdf", rows)).parse()
    assert all(t.parsed_amount_minor > 0 for t in result.transactions)  # unsigned, as printed


# --- spreadsheet export ------------------------------------------------------------

HEADERS = ["TransactionDate", "Text", "Type", "Currency Amount", "Currency Rate", "Currency", "Amount",
           "Merchant Area", "Merchant Category", "BookDate", "ValueDate"]


def _export_row(tx_day, book_day, text, typ, amount, area, mcc, currency="EUR", currency_amount=None):
    return [datetime(2026, 9, tx_day), text, typ, currency_amount if currency_amount is not None else amount, 1,
            currency, amount, area, mcc, datetime(2026, 9, book_day), datetime(2026, 9, book_day)]


EXPORT_ROWS = [
    _export_row(1, 1, f"Max Muster {CARD_IBAN}", "Einzahlung", 300, None, None),
    _export_row(1, 2, "REWE Markt Beispiel", "Einkauf", -42.9, "Bochum", "GROCERY STORES/SUPERMARKETS"),
    _export_row(3, 4, "Gutschrift Lastschrift Beispiel", "Einkauf", -5, "Beispielstadt", "MISC SPECIALTY RETAIL"),
    _export_row(4, 5, "Online Shop Beispiel", "Gutschrift", 19.99, "shop.example", "FAMILY CLOTHING STORES"),
    _export_row(6, 7, "Baeckerei Beispiel Sohn", "Einkauf", -1234.5, "0301234567", "BAKERIES"),
    # paid abroad: "Currency"/"Currency Amount" describe the original amount, "Amount" is in EUR
    _export_row(8, 9, "Hotel Example London", "Einkauf", -117.3, "London", "HOTELS/MOTELS/RESORTS", "GBP", -100),
]


def test_camel_case_and_spacing_variants_of_headers():
    assert normalize_header("TransactionDate") == "transaction date"
    assert normalize_header("BookDate") == "book date"
    mapping = detect_columns(["BuchungsDatum", "Verwendungszweck", "Betrag"])
    assert mapping["date"] == "BuchungsDatum"


def test_card_export_columns(tmp_path):
    fmt = detect_bank_format(HEADERS)
    assert fmt is not None and fmt.name == "Card export with merchant category"
    mapping = detect_columns(HEADERS)
    assert mapping["date"] == "BookDate"          # same date as the PDF statement shows
    assert mapping["value_date"] == "ValueDate"
    assert mapping["payee"] is None               # "Merchant Area" is the merchant's town
    assert mapping["currency"] is None            # belongs to "Currency Amount", not to "Amount"
    assert mapping["merchant_category"] == "Merchant Category"

    result = XLSXImporter(write_xlsx(tmp_path / "export.xlsx", HEADERS, EXPORT_ROWS)).parse()
    assert not result.ambiguous and not result.has_errors
    tx = result.transactions
    assert [t.parsed_amount_minor for t in tx] == [30000, -4290, -500, 1999, -123450, -11730]
    assert all(t.parsed_currency is None for t in tx)  # -> the account's currency (EUR)
    assert tx[1].parsed_date == "2026-09-02"
    assert tx[1].extra_fields["_merchant_category"] == "GROCERY STORES/SUPERMARKETS"
    assert tx[0].extra_fields["_booking_text"] == "Einzahlung"
    assert all(t.counterparty is None for t in tx)


@pytest.mark.parametrize(("label", "category"), [
    ("GROCERY STORES/SUPERMARKETS", "Groceries"),
    ("MISC FOOD STORES - DEFAULT", "Groceries"),
    ("RESTAURANTS", "Food"),
    ("FAST FOOD RESTAURANTS", "Food"),
    ("BAKERIES", "Food"),
    ("DRUG STORES  PHARMACIES", "Health"),
    ("PASSENGER RAILWAYS", "Transport"),
    ("PARKING LOTS  GARAGES", "Transport"),
    ("SERVICE STATIONS", "Transport"),
    ("AIRLINES, AIR CARRIERS", "Travel"),
    ("HOTELS/MOTELS/RESORTS", "Travel"),
    ("VIDEO AMUSEMENT GAME SUPPLY", "Entertainment"),
    ("FAMILY CLOTHING STORES", "Shopping"),
    ("TELECOMMUNICATION EQUIPMENT", "Shopping"),
    ("WIRE TRANSFER MONEY ORDER", None),
    ("COMPUTER PROGRAM/SYS DESIGN", None),
    (None, None),
])
def test_merchant_category_mapping(label, category):
    assert category_from_merchant_category(label) == category


# --- through the API -------------------------------------------------------------------

def _account(client, name, account_type, iban=None):
    body = {"name": name, "account_type": account_type}
    if iban:
        body["iban"] = iban
    r = client.post("/api/accounts", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _import(client, account_id, name, content, mime):
    files = {"file": (name, io.BytesIO(content), mime)}
    preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id})
    assert preview.status_code == 200, preview.text
    p = preview.json()
    commit = client.post("/api/imports/commit", json={"staging_id": p["staging_id"], "account_id": account_id})
    assert commit.status_code == 200, commit.text
    return p, commit.json()


def _transactions(client, account_id):
    return client.get("/api/transactions", params={"account_id": account_id, "page_size": 100}).json()["items"]


def test_pdf_then_export_of_the_same_month(client, tmp_path):
    """Both sources of one card account: the export's rows are recognized as
    the PDF's bookings (despite "&" missing in the export), and what only the
    export knows — merchant category, booking type — is added to them."""
    card = _account(client, "Karte", "credit_card", CARD_IBAN)
    pdf = write_table_pdf(tmp_path / "card.pdf", STATEMENT_ROWS)
    preview, _ = _import(client, card, "card.pdf", pdf.read_bytes(), "application/pdf")
    # an account-style PDF on a card account: a warning to confirm, not a refusal
    assert [i["severity"] for i in preview["issues"]] == ["warning"]

    by_amount = {t["amount_minor"]: t for t in _transactions(client, card)}
    assert by_amount[30000]["transaction_type"] == "transfer"   # top-up names an IBAN: not a refund
    assert by_amount[1999]["transaction_type"] == "expense"     # refund: reduces spending
    assert by_amount[-4290]["category"] == "Groceries"          # name rule

    xlsx = write_xlsx(tmp_path / "export.xlsx", HEADERS, EXPORT_ROWS[:5])
    preview, commit = _import(client, card, "export.xlsx", xlsx.read_bytes(),
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert (preview["new_count"], preview["exact_duplicate_count"], preview["possible_duplicate_count"]) == (0, 5, 0)
    assert commit["transactions_created"] == 0

    after = {t["amount_minor"]: t for t in _transactions(client, card)}
    assert len(after) == 5
    assert after[-123450]["category"] == "Food"        # was "Other Expense": the export's "BAKERIES"
    assert after[1999]["category"] == "Shopping"       # refund, sorted like the purchase
    assert after[-500]["category"] == "Shopping"
    # the export's merchant town column tells where the PDF's bookings took place
    assert (after[-4290]["country"], after[-4290]["city"]) == ("DE", "Bochum")
    assert after[1999]["online"] is True and after[1999]["country"] is None   # "shop.example"
    assert after[-500]["country"] is None        # "Beispielstadt": no known town
    assert after[-123450]["country"] is None     # a phone number: place unknown
    assert after[30000]["country"] is None       # the top-up


def test_export_first_categorizes_by_merchant_category(client, tmp_path):
    card = _account(client, "Karte", "credit_card", CARD_IBAN)
    xlsx = write_xlsx(tmp_path / "export.xlsx", HEADERS, EXPORT_ROWS)
    _import(client, card, "export.xlsx", xlsx.read_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    by_amount = {t["amount_minor"]: t for t in _transactions(client, card)}
    assert by_amount[30000]["transaction_type"] == "transfer"   # booking type "Einzahlung"
    assert by_amount[-11730]["category"] == "Travel" and by_amount[-11730]["currency"] == "EUR"
    assert (by_amount[-11730]["country"], by_amount[-11730]["city"]) == ("GB", "London")
    assert by_amount[-123450]["category"] == "Food"


def test_card_top_up_is_paired_with_the_bank_debit_but_a_refund_is_not(client, tmp_path):
    giro = _account(client, "Giro", "checking", GIRO_IBAN)
    card = _account(client, "Karte", "credit_card", CARD_IBAN)
    bank_csv = (
        "Buchungstag;Verwendungszweck;Betrag\n"
        f"31.08.2026;Ueberweisung an Karte {CARD_IBAN};-300,00\n"
        "05.09.2026;Kartenzahlung Online Shop Beispiel;-19,99\n"
    ).encode()
    _import(client, giro, "giro.csv", bank_csv, "text/csv")
    _import(client, card, "card.pdf", write_table_pdf(tmp_path / "card.pdf", STATEMENT_ROWS).read_bytes(),
            "application/pdf")

    giro_tx = {t["amount_minor"]: t for t in _transactions(client, giro)}
    card_tx = {t["amount_minor"]: t for t in _transactions(client, card)}
    assert giro_tx[-30000]["transaction_type"] == "transfer"    # not counted as an expense
    assert card_tx[30000]["transaction_type"] == "transfer"
    assert giro_tx[-1999]["transaction_type"] == "expense"      # same amount as the refund, but no transfer
    assert card_tx[1999]["transaction_type"] == "expense"
    # a recognized payment onto the card needs no category review
    assert (giro_tx[-30000]["category"], giro_tx[-30000]["needs_review"]) == ("Transfers", False)

    totals = client.get("/api/analytics/totals").json()
    assert totals["expenses_minor"] == 1999 + 4290 + 500 + 123450 - 1999


def test_payments_onto_a_card_need_no_review_and_are_sorted_again_when_released(client, tmp_path):
    """A bank debit to the card's bank is unsorted ("Other Expense", to
    review) until it is paired with the payment arriving on the card; the
    pairing files it under Transfers. Undone, it is an ordinary debit again."""
    from sqlmodel import Session

    import app.db.session as db_session
    from app.db.models import Transaction
    from app.services.transfer_detection_service import unpair_transfer
    from app.services.transfer_marking import settle_flagged_transfers

    giro = _account(client, "Giro", "checking")
    card = _account(client, "Karte", "credit_card")
    _import(client, giro, "giro.csv", (
        b"Buchungstag;Verwendungszweck;Betrag\n"
        b"30.09.2026;Kartenbank Beispiel Rueckzahlung;-191,02\n"
    ), "text/csv")
    before = _transactions(client, giro)[0]
    assert (before["category"], before["needs_review"]) == ("Other Expense", True)

    xlsx = write_xlsx(tmp_path / "export.xlsx", HEADERS, [
        _export_row(30, 30, "Max Muster", "Einzahlung", 191.02, None, None),
    ])
    _import(client, card, "export.xlsx", xlsx.read_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    debit = _transactions(client, giro)[0]
    assert debit["transaction_type"] == "transfer"
    assert (debit["category"], debit["needs_review"]) == ("Transfers", False)
    assert client.get("/api/transactions", params={"needs_review": True}).json()["total"] == 0

    with Session(db_session.engine) as session:
        tx = session.get(Transaction, debit["id"])
        partner = session.get(Transaction, tx.transfer_pair_id)
        unpair_transfer(session, partner)
        session.commit()
        session.refresh(tx)
        assert (tx.transaction_type.value, tx.category, tx.needs_review) == ("expense", "Other Expense", True)

        # transfers flagged by an older version are cleared on start-up
        tx.is_transfer, tx.needs_review = True, True
        session.add(tx)
        session.commit()
        settle_flagged_transfers(session)
        session.refresh(tx)
        assert (tx.category, tx.needs_review) == ("Transfers", False)


def test_card_page_counts_linked_payments_of_a_card_without_statements(client, tmp_path):
    giro = _account(client, "Giro", "checking")
    card = _account(client, "Karte", "credit_card")
    _import(client, giro, "giro.csv", (
        b"Buchungstag;Verwendungszweck;Betrag\n30.09.2026;Kartenbank Beispiel Rueckzahlung;-191,02\n"
    ), "text/csv")
    xlsx = write_xlsx(tmp_path / "export.xlsx", HEADERS, [
        _export_row(30, 30, "Max Muster", "Einzahlung", 191.02, None, None),
        _export_row(2, 2, "Max Muster", "Einzahlung", 50, None, None),   # no bank statement for it
        _export_row(5, 5, "Baeckerei Beispiel", "Einkauf", -4.2, "Bochum", "BAKERIES"),
    ])
    _import(client, card, "export.xlsx", xlsx.read_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    summary = next(c for c in client.get("/api/credit-cards").json() if c["account"]["id"] == card)
    assert (summary["statement_count"], summary["payments_linked"], summary["payments_unlinked"]) == (0, 1, 1)


def test_removing_one_of_two_files_with_the_same_bookings_keeps_them(client, tmp_path):
    """The PDF and the export of one month hold the same bookings; the
    export's rows were skipped as duplicates. Removing the PDF must leave
    the bookings in place (now belonging to the export), not delete them."""
    card = _account(client, "Karte", "credit_card", CARD_IBAN)
    pdf = write_table_pdf(tmp_path / "card.pdf", STATEMENT_ROWS)
    _import(client, card, "card.pdf", pdf.read_bytes(), "application/pdf")
    xlsx = write_xlsx(tmp_path / "export.xlsx", HEADERS, EXPORT_ROWS[:5])
    _import(client, card, "export.xlsx", xlsx.read_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    before = {t["amount_minor"]: t for t in _transactions(client, card)}

    imports = {i["filename"]: i["id"] for i in client.get("/api/imports").json()}
    assert client.delete(f"/api/imports/{imports['card.pdf']}").status_code == 200
    after = {t["amount_minor"]: t for t in _transactions(client, card)}
    assert sorted(after) == sorted(before)
    assert after[-123450]["category"] == "Food" and after[30000]["transaction_type"] == "transfer"
    assert all(t["source_filename"] == "export.xlsx" for t in after.values())

    # importing the PDF again recognizes the bookings instead of doubling them
    preview, commit = _import(client, card, "card.pdf", pdf.read_bytes(), "application/pdf")
    assert commit["transactions_created"] == 0 and len(_transactions(client, card)) == 5

    assert client.delete(f"/api/imports/{imports['export.xlsx']}").status_code == 200
    assert len(_transactions(client, card)) == 5  # still in the PDF
