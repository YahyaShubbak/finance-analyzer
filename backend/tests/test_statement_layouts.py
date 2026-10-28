"""Statement layouts as found in real bank and card PDFs, rebuilt from
their STRUCTURE with invented content (no real data):

* a card statement in the American-Express style — "dd.mm dd.mm" dates,
  unsigned amounts, credits marked by a "GUTSCHRIFT" line below the
  booking, the title split into separate words, and "Saldo des laufenden
  Monats" as the statement total;
* a bank statement where every booking is a block: booking line with the
  signed amount, then a value-date line naming payee/purpose, then
  reference lines.
"""
from __future__ import annotations

import io

from sqlmodel import select

from app.db.models import Account, AccountType, CategoryRule, DocumentType, MerchantRule, Transaction
from app.importers.pdf_importer import PDFImporter
from app.normalization.category import CARD_ACCOUNT_EXCLUDED, DEFAULT_CATEGORY_RULES, categorize
from app.normalization.merchant import DEFAULT_MERCHANT_RULES, normalize_merchant
from app.reconciliation.engine import reconcile_statement
from app.services.import_service import commit_parsed_import
from tests.pdf_fixtures import write_text_pdf

CARD_LINES = [
    "Ihre Karte",
    "American Express Gold",
    "Abrechnung vom 22/09/26",
    "Saldo der letzten Abrechnung Gutschriften Neue Belastungen Neuer Saldo",
    "Umsatz vom Beschreibung Betrag in Fremdwaehrung Betrag EUR",
    "01.09 02.09 ZAHLUNG/UEBERWEISUNG ERHALTEN BESTEN DANK 250,00",
    "Ref. 000000000001 GUTSCHRIFT",
    "03.09 04.09 BAECKEREI BEISPIEL BERLIN 4,80",
    "05.09 06.09 REWE MARKT BEISPIEL 32,40",
    "07.09 08.09 ONLINE SHOP RUECKGABE 12,00",
    "000000000002 0000000003 GUTSCHRIFT",
    "10.09 11.09 PAYPAL *SPOTIFY 10,99",
    "15.09 16.09 HOTEL BEISPIEL LONDON 184,33",
    "Saldo des laufenden Monats fuer Karte 220,52",
]

BANK_LINES = [
    "Girokonto Kontoauszug",
    "IBAN DE02 1203 0000 0000 2020 51",
    "Zeitraum: 01.09.2026 - 30.09.2026",
    "Buchungstag Valuta Vorgang Betrag",
    "02.09.2026 Lastschrift / Belastung -32,40",
    "02.09.2026 REWE Markt GmbH Einkauf 12,34 EUR vom 01.09.",
    "EREF+000000000001",
    "MREF+AB12345",
    "05.09.2026 Gutschrift / Ueberweisung +1.500,00",
    "05.09.2026 Arbeitgeber AG Gehalt September",
    "10.09.2026 Lastschrift / Belastung -220,52",
    "10.09.2026 American Express Europe S.A.",
    "12.09.2026 Dauerauftrag Miete -700,00 EUR Ref. 2026/09",
    "Kontostand am 30.09.2026 +547,08",
]


def test_amex_style_card_statement(tmp_path):
    result = PDFImporter(write_text_pdf(tmp_path / "card.pdf", CARD_LINES)).parse()

    assert result.document_type == DocumentType.CREDIT_CARD_STATEMENT
    assert not result.has_errors and not [i for i in result.issues if i.severity == "warning"
                                           and "could not be read" in i.message]
    amounts = [t.parsed_amount_minor for t in result.transactions]
    # payment and return are credits (positive), everything else a charge
    assert amounts == [25000, -480, -3240, 1200, -1099, -18433]
    assert [t.parsed_date for t in result.transactions][0] == "2026-09-01"
    assert result.statement_total_minor == 22052  # charges minus the return, without the payment


def test_amex_style_statement_reconciles_with_the_bank_debit(session, tmp_path):
    card = Account(name="Card", account_type=AccountType.CREDIT_CARD)
    bank = Account(name="Giro", account_type=AccountType.CHECKING)
    session.add_all([card, bank])
    session.commit()

    card_result = PDFImporter(write_text_pdf(tmp_path / "card.pdf", CARD_LINES)).parse()
    commit = commit_parsed_import(session, card_result, card.id, stored_path="")
    payment_line = session.exec(select(Transaction).where(Transaction.amount_minor == 25000)).one()
    assert payment_line.is_transfer  # the card being paid off, not income

    bank_result = PDFImporter(write_text_pdf(tmp_path / "bank.pdf", BANK_LINES)).parse()
    commit_parsed_import(session, bank_result, bank.id, stored_path="")

    rec = reconcile_statement(session, commit.credit_card_statement.id)
    assert rec.status.value == "reconciled"
    assert rec.diff_transactions_vs_statement_minor == 0


def test_bank_statement_booking_blocks(tmp_path):
    result = PDFImporter(write_text_pdf(tmp_path / "bank.pdf", BANK_LINES)).parse()

    assert result.document_type == DocumentType.BANK_STATEMENT
    tx = result.transactions
    assert [t.parsed_amount_minor for t in tx] == [-3240, 150000, -22052]
    # the value-date line names the payee and becomes part of the description
    assert "REWE Markt GmbH" in tx[0].original_description
    assert tx[0].extra_fields["_value_date"] == "2026-09-02"
    assert "EREF" in tx[0].extra_fields["_details"]
    assert "Arbeitgeber AG" in tx[1].original_description
    # a dated line with a signed amount is its own (unreadable) booking,
    # never glued onto the previous one — and it is reported
    assert "Miete" not in tx[2].original_description
    assert any("could not be read as a transaction" in i.message for i in result.issues)


def test_rules_for_the_new_categories():
    rules = [CategoryRule(id=i, pattern=p, is_regex=True, match_field="any", category=c, amount_sign=s, priority=pr)
             for i, (p, c, s, pr) in enumerate(DEFAULT_CATEGORY_RULES)]
    merchant_rules = [MerchantRule(id=i, pattern=p, is_regex=True, normalized_merchant=n)
                      for i, (p, n) in enumerate(DEFAULT_MERCHANT_RULES)]

    def category(description, amount, **kwargs):
        return categorize(normalize_merchant(description, merchant_rules), description, amount, rules, **kwargs)

    assert category("Bargeldauszahlung Geldautomat", -5000) == "Cash"
    assert category("Entgelt Kontofuehrung", -495) == "Fees"
    assert category("Spende Beispielverein", -1000) == "Donations"
    assert category("Studierendenwerk Mensa", -450) == "Food"
    assert category("Studierendenwerk Miete Zimmer", -30000) == "Housing"
    assert category("Arbeitsentgelt September", 200000) == "Salary"
    assert category("American Express Europe S.A.", -22052) == "Card bills"
    # ... but not on the card account itself (e.g. the card's annual fee)
    assert category("AMEX Jahresgebuehr", -5500, exclude=CARD_ACCOUNT_EXCLUDED) != "Card bills"


def test_paypal_shows_the_merchant_behind_it():
    merchant_rules = [MerchantRule(id=i, pattern=p, is_regex=True, normalized_merchant=n)
                      for i, (p, n) in enumerate(DEFAULT_MERCHANT_RULES)]
    assert normalize_merchant("PAYPAL *SPOTIFY 35314369001", merchant_rules) == "Spotify"
    assert normalize_merchant("PayPal Europe S.a.r.l. 1234 PP.1.PP . Ihr Einkauf bei Beispiel Shop", merchant_rules) \
        == "Beispiel Shop"
    assert normalize_merchant("PayPal Europe S.a.r.l.", merchant_rules) == "PayPal"


# --- the statement checks itself ---------------------------------------------------------

def test_bank_statement_balance_check(tmp_path):
    lines = [
        "Girokonto Kontoauszug",
        "Zeitraum: 01.09.2026 - 30.09.2026",
        "Alter Saldo 31.08.2026 +1.000,00",
        "02.09.2026 Lastschrift / Belastung -32,40",
        "02.09.2026 REWE Markt GmbH Einkauf",
        "05.09.2026 Gutschrift / Ueberweisung +1.500,00",
        "05.09.2026 Arbeitgeber AG Gehalt September",
        "Neuer Saldo 30.09.2026 +2.467,60",
        # a second sub-account without bookings
        "Alter Saldo 31.08.2026 +5,00",
        "Neuer Saldo 30.09.2026 +5,00",
    ]
    ok = PDFImporter(write_text_pdf(tmp_path / "ok.pdf", lines)).parse()
    assert ok.total_check == {"kind": "balance", "ok": True, "difference_minor": 0}
    assert not [i for i in ok.issues if i.severity == "warning"]

    lines[7] = "Neuer Saldo 30.09.2026 +2.500,00"  # a booking of 32,40 is "missing"
    off = PDFImporter(write_text_pdf(tmp_path / "off.pdf", lines)).parse()
    assert off.total_check == {"kind": "balance", "ok": False, "difference_minor": 3240}
    assert any("don't add up" in i.message for i in off.issues)


def test_card_statement_total_check_in_preview(client, tmp_path):
    card = client.post("/api/accounts", json={"name": "Card", "account_type": "credit_card"}).json()["id"]
    pdf = write_text_pdf(tmp_path / "card.pdf", CARD_LINES)
    with open(pdf, "rb") as f:
        preview = client.post("/api/imports/preview", files={"file": ("card.pdf", f, "application/pdf")},
                              data={"account_id": card}).json()
    assert preview["total_check"] == {"kind": "statement_total", "ok": True, "difference_minor": 0}


def test_card_csv_first_then_the_statement_pdf(client, tmp_path):
    """The card's CSV export (purchases as positive numbers) imported before
    the PDF statement of the same month: the export's signs are corrected,
    the statement's rows are recognized as the same bookings, and the
    reconciliation still finds the statement's purchases."""
    card = client.post("/api/accounts", json={"name": "Amex", "account_type": "credit_card"}).json()["id"]
    csv = (
        b"Datum,Beschreibung,Betrag\n"
        b'01/09/2026,ZAHLUNG/UEBERWEISUNG ERHALTEN BESTEN DANK,"-250,00"\n'
        b'03/09/2026,BAECKEREI BEISPIEL BERLIN,"4,80"\n'
        b'05/09/2026,REWE MARKT BEISPIEL,"32,40"\n'
        b'07/09/2026,ONLINE SHOP RUECKGABE,"-12,00"\n'
        b'10/09/2026,PAYPAL *SPOTIFY,"10,99"\n'
        b'15/09/2026,HOTEL BEISPIEL LONDON,"184,33"\n'
    )
    preview = client.post("/api/imports/preview", files={"file": ("amex.csv", io.BytesIO(csv), "text/csv")},
                          data={"account_id": card}).json()
    assert [t["parsed_amount_minor"] for t in preview["transactions"]] == [25000, -480, -3240, 1200, -1099, -18433]
    client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": card})

    pdf = write_text_pdf(tmp_path / "card.pdf", CARD_LINES)
    with open(pdf, "rb") as f:
        preview = client.post("/api/imports/preview", files={"file": ("card.pdf", f, "application/pdf")},
                              data={"account_id": card}).json()
    assert (preview["new_count"], preview["exact_duplicate_count"]) == (0, 6)
    statement_id = client.post("/api/imports/commit", json={"staging_id": preview["staging_id"],
                                                             "account_id": card}).json()["credit_card_statement_id"]
    detail = client.get(f"/api/reconciliation/statements/{statement_id}").json()
    assert detail["diff_transactions_vs_statement_minor"] == 0
    assert len(detail["transactions"]) == 6
    assert len(client.get("/api/transactions").json()["items"]) == 6


# --- a number in the booking text right before the amount ----------------------------------

def _bank(lines):
    return ["Girokonto Kontoauszug", "Zeitraum: 01.09.2026 - 30.09.2026", "Alter Saldo 31.08.2026 +1.000,00",
            *lines]


def test_number_in_the_text_before_the_amount_is_not_the_amount(tmp_path):
    """Statements without a balance column (e.g. comdirect): a line ending in
    "12 345,67 -345,67" books -345,67; "12 345,67" is part of the text."""
    lines = _bank([
        "02.09.2026 Lastschrift / Belastung Stadtwerke Rechnung 12 345,67 -345,67",
        "03.09.2026 Lastschrift / Belastung Versand Paket 12 99,99 -99,99",
        "05.09.2026 Gutschrift / Ueberweisung Arbeitgeber AG +1.500,00",
        "06.09.2026 Lastschrift / Belastung REWE Markt -32,40",
        "Neuer Saldo 30.09.2026 +2.021,94",
    ])
    result = PDFImporter(write_text_pdf(tmp_path / "bank.pdf", lines)).parse()
    assert [t.parsed_amount_minor for t in result.transactions] == [-34567, -9999, 150000, -3240]
    assert "12 345,67" in result.transactions[0].original_description
    assert result.total_check == {"kind": "balance", "ok": True, "difference_minor": 0}


def test_balances_decide_an_ambiguous_line(tmp_path):
    lines = _bank([
        "02.09.2026 Gutschrift Erstattung 2 Stueck +5,00 +12,00",  # both signed: which is the booking?
        "06.09.2026 Lastschrift / Belastung REWE Markt -32,40",
        "Neuer Saldo 30.09.2026 +979,60",                            # only +12,00 adds up
    ])
    result = PDFImporter(write_text_pdf(tmp_path / "bank.pdf", lines)).parse()
    assert [t.parsed_amount_minor for t in result.transactions] == [1200, -3240]
    assert result.total_check["ok"]


def test_summary_box_headings_do_not_sign_the_bookings(tmp_path):
    """A card statement's summary box ("Gutschriften | Neue Belastungen")
    is not the booking table: its headings must not sign the bookings."""
    from app.importers.pdf_importer import _amount_columns
    from tests.pdf_fixtures import write_table_pdf
    rows = [
        [(60, "Kreditkartenabrechnung", "l")],
        [(60, "Abrechnungszeitraum: 01.09.2026 - 30.09.2026", "l")],
        [(250, "Gutschriften", "r"), (350, "Belastungen", "r"), (450, "Neuer Saldo", "r")],
        [(250, "12,00", "r"), (350, "37,20", "r"), (450, "25,20", "r")],
        [],
        [(60, "03.09.2026", "l"), (130, "REWE MARKT BEISPIEL", "l"), (540, "32,40", "r")],
        [(60, "05.09.2026", "l"), (130, "BAECKEREI BEISPIEL", "l"), (540, "4,80", "r")],
        [(60, "07.09.2026", "l"), (130, "ONLINE SHOP RUECKGABE", "l"), (540, "-12,00", "r")],
        [(60, "Neuer Saldo", "l"), (540, "25,20", "r")],
    ]
    path = write_table_pdf(tmp_path / "card.pdf", rows)
    import pymupdf
    with pymupdf.open(path) as doc:
        assert _amount_columns([page.get_text("words") for page in doc]) is None
    result = PDFImporter(path).parse()
    assert [t.parsed_amount_minor for t in result.transactions] == [-3240, -480, 1200]


def test_card_statement_with_the_direction_after_the_amount(tmp_path):
    """Layout of e.g. Landesbank Berlin's card statements (invented content):
    purchase date, text, booking date, amount and then "-" (charge) or "+"
    (credit) apart from it; the payment onto the card has no purchase date;
    reward-points lines between the bookings."""
    from app.importers.pdf_importer import PDFImporter
    from tests.pdf_fixtures import write_text_pdf

    path = write_text_pdf(tmp_path / "karte.pdf", [
        "Beispielbank KartenService",
        "Ihre Kreditkartenabrechnung vom 12.08.2026",
        "Alter Kontostand: 100,00 -",
        "Gutschriften: 102,00 +",
        "Ausgaben: 32,50 -",
        "Neuer Kontostand: 30,50 -",
        "Kaufdatum Umsatz/Ort Buchungsdatum Währung Betrag Kurs Betrag in Euro",
        "ZAHLUNG-LASTSCHRIFT 18.07.2026 100,00 +",
        "Visa Karte 1234 56XX XXXX 7890 MAX MUSTER",
        "11.07.2026 Baeckerei Muster Bochum 12.07.2026 8,50 -",
        "+4 BONUS PUNKTE",
        "13.07.2026 Buchhandlung Beispiel 15.07.2026 24,00 -",
        "+12 BONUS PUNKTE",
        "19.07.2026 AMZ*Beispiel Versand 22.07.2026 2,00 +",
        "Neuer Kontostand 30,50 -",
    ])
    result = PDFImporter(path).parse()
    assert result.document_type.value == "credit_card_statement"
    assert [i.message for i in result.issues] == []
    rows = [(t.parsed_date, t.extra_fields.get("_value_date"), t.parsed_amount_minor, t.original_description)
            for t in result.transactions]
    assert rows == [
        ("2026-07-18", None, 10000, "ZAHLUNG-LASTSCHRIFT"),          # the payment onto the card
        ("2026-07-11", "2026-07-12", -850, "Baeckerei Muster Bochum"),
        ("2026-07-13", "2026-07-15", -2400, "Buchhandlung Beispiel"),
        ("2026-07-19", "2026-07-22", 200, "AMZ*Beispiel Versand"),    # a credit
    ]
    assert result.statement_total_minor == 3050 and result.other_totals == {"previous_balance": 10000}


def test_card_statement_titled_kartenabrechnung_with_a_debit_iban(tmp_path):
    """"Ihre Kartenabrechnung vom …" is a card statement, even though its
    header names the giro IBAN the bill is debited from."""
    path = write_text_pdf(tmp_path / "karte.pdf", [
        "Ihre Kartenabrechnung vom 12.08.2026",
        "Kontoübersicht Euro",
        "Alter Kontostand: 50,00 -",
        "Neuer Kontostand: 42,50 -",
        "Der Betrag von 42,50 Euro wird am 19.08.2026 abgebucht. IBAN: DE02120300000000202051",
        "Kaufdatum Umsatz/Ort Buchungsdatum Betrag in Euro",
        "13.07.2026 Buchladen Beispiel 14.07.2026 12,50 -",
        "+12 SHOP PUNKTE",
        "20.07.2026 Rückgabe Kiosk Muster 21.07.2026 20,00 +",
    ])
    result = PDFImporter(path, path.name).parse()
    assert result.document_type == DocumentType.CREDIT_CARD_STATEMENT
    assert [t.parsed_amount_minor for t in result.transactions] == [-1250, 2000]
    assert not any(line["role"] == "unreadable" for line in result.layout_lines)


def test_card_statement_ending_in_a_credit_balance(tmp_path):
    """Paid in more than spent: the new balance is a credit ("+"), nothing is
    debited — and the statement still checks itself against its balances."""
    path = write_text_pdf(tmp_path / "guthaben.pdf", [
        "Ihre Kartenabrechnung vom 12.09.2026",
        "Alter Kontostand 50,00 -",
        "Kaufdatum Umsatz/Ort Buchungsdatum Betrag in Euro",
        "ZAHLUNG-LASTSCHRIFT 19.08.2026 50,00 +",
        "GUTHABENEINZAHLUNG 21.08.2026 100,00 +",
        "13.08.2026 Buchladen Beispiel 14.08.2026 12,50 -",
        "Neuer Kontostand 87,50 +",
    ])
    result = PDFImporter(path, path.name).parse()
    assert result.statement_total_minor == 0
    assert result.total_check == {"kind": "balance", "ok": True, "difference_minor": 0}


def test_a_statement_with_nothing_owed_needs_no_debit(session):
    from datetime import date

    from app.db.models import CreditCardStatement, ImportRecord, ImportStatus, ReconciliationStatus
    from app.reconciliation.engine import compute_reconciliation, find_candidate_bank_debits

    card = Account(name="Karte", account_type=AccountType.CREDIT_CARD)
    session.add(card)
    session.flush()
    record = ImportRecord(filename="k.pdf", stored_path="k.pdf", file_checksum="x", document_type=DocumentType.CREDIT_CARD_STATEMENT,
                          account_id=card.id, status=ImportStatus.IMPORTED, detected_transaction_count=0)
    session.add(record)
    session.flush()
    statement = CreditCardStatement(account_id=card.id, import_id=record.id, statement_period_end=date(2026, 9, 12),
                                    statement_total_minor=0)
    session.add(statement)
    session.flush()
    assert find_candidate_bank_debits(session, statement) == []
    assert compute_reconciliation(session, statement, None).status == ReconciliationStatus.RECONCILED


def test_a_fee_line_under_a_purchase_is_its_own_booking(tmp_path):
    """"AUSLANDSEINSATZENTGELT 0,61 -" printed under a foreign purchase,
    without a date: a booking of its own, on the purchase's date."""
    path = write_text_pdf(tmp_path / "fee.pdf", [
        "Ihre Kreditkartenabrechnung vom 10.02.2026",
        "Alter Kontostand 10,00 -",
        "Kaufdatum Umsatz/Ort Buchungsdatum Betrag in Euro",
        "ZAHLUNG-LASTSCHRIFT 18.01.2026 10,00 +",
        "16.01.2026 Buchladen Beispiel 17.01.2026 34,74 -",
        "+17 SHOP PUNKTE",
        "AUSLANDSEINSATZENTGELT 0,61 -",
        "Neuer Kontostand 35,35 -",
    ])
    result = PDFImporter(path, path.name).parse()
    got = [(t.parsed_date, t.original_description, t.parsed_amount_minor) for t in result.transactions]
    assert got[-1] == ("2026-01-16", "AUSLANDSEINSATZENTGELT", -61)
    assert result.total_check == {"kind": "balance", "ok": True, "difference_minor": 0}


def test_running_text_starting_with_a_date_is_no_missed_booking():
    """A report's news text may start a line with a date ("... ist nur noch
    bis / 31.05.2026 erhältlich. Sichern Sie sich ..."): no booking, no
    warning. A line with an amount besides its dates still is one."""
    from app.importers.pdf_layouts.patterns import may_be_missed_booking

    assert not may_be_missed_booking("31.05.2026 erhältlich. Sichern Sie sich daher jetzt noch ein letztes Mal garantierte 3 % p. a.")
    assert not may_be_missed_booking("31.05.2026 (2)")  # the date itself is no amount
    assert not may_be_missed_booking("15.03.2026 bis 31.03.2026")
    assert may_be_missed_booking("13.07.2026 KIOSK MUSTER VALENCIA ES 14.07.2026 16,93 -")
    assert may_be_missed_booking("02.03.2026 Lastschrift / Belastung Stadtwerke Beispiel GmbH Abschlag 45,00")
    assert may_be_missed_booking("02.03.2026 Überweisung an Erika Muster für die Miete vom Februar 650,00")
    assert may_be_missed_booking("21.05 21.05 BUCHLADEN MUSTER 3,65 X")


def _invoice(tmp_path, name, previous, payments, total):
    """A card invoice like Bank Norwegian's: a summary with the previous
    period's amount and the new total (a date after its label), then a table
    whose "Summe" column holds purchases positive, payments and refunds negative."""
    from tests.pdf_fixtures import write_table_pdf

    def summary(label, amount):
        return [(40, label, "l"), (430, "EUR", "l"), (545, amount, "r")]

    rows = [
        [(300, "Rechnung", "l")], [(300, "Beispielbank-Karte", "l")],
        [(360, "Rechnungszeitraum 16.09.26 - 15.10.26", "l")],
        summary("Rechnungsbetrag der Vorperiode", previous),
        summary("Einzahlungen im Zeitraum 16.09.26 - 15.10.26", payments),
        summary("Summe der Transaktionen des Zeitraums", "60,00"),
        summary("Gesamtbetrag 15.10.2026", total),
        summary("Fälliger Mindestbetrag", "30,00"),
        [],
        [(25, "Datum", "l"), (73, "Händler", "l"), (264, "Kartennummer", "l"), (402, "Betrag", "r"), (583, "Summe", "r")],
    ]
    if payments != "0,00":
        rows.append([(25, "30.09.2026", "l"), (73, "Payment", "l"), (583, payments, "r")])
    for day, merchant, amount, booked in [("19.09.2026", "PARKHAUS MUSTER ,Bremen", "25,00", "25,00"),
                                          ("21.09.2026", "BUCHLADEN BEISPIEL ,Bremen", "45,00", "45,00"),
                                          ("09.10.2026", "BUCHLADEN BEISPIEL ,Bremen", "10,00", "-10,00")]:
        rows.append([(25, day, "l"), (73, merchant, "l"), (264, "123456******9999", "l"), (402, amount, "r"), (583, booked, "r")])
    return write_table_pdf(tmp_path / name, rows)


def test_card_invoice_with_previous_period_and_total_after_a_date(tmp_path):
    path = _invoice(tmp_path, "rechnung.pdf", previous="80,00", payments="-80,00", total="60,00")
    result = PDFImporter(path, path.name).parse()
    assert result.document_type == DocumentType.CREDIT_CARD_STATEMENT
    # the previous period's amount is not this statement's amount
    assert result.statement_total_minor == 6000 and result.other_totals["previous_balance"] == 8000
    assert [t.parsed_amount_minor for t in result.transactions] == [8000, -2500, -4500, 1000]
    assert result.total_check == {"kind": "balance", "ok": True, "difference_minor": 0}


def test_card_invoice_after_a_credit_balance(tmp_path):
    """Paid in more than owed: the previous period printed negative (a credit)."""
    path = _invoice(tmp_path, "guthaben.pdf", previous="-20,00", payments="0,00", total="40,00")
    result = PDFImporter(path, path.name).parse()
    assert result.statement_total_minor == 4000
    assert result.total_check == {"kind": "balance", "ok": True, "difference_minor": 0}


def test_stored_statements_get_the_totals_the_reader_finds_now(client, tmp_path):
    from sqlmodel import select

    from app.config import settings
    from app.db.models import CreditCardStatement
    from app.db.session import session_scope
    from app.services.statement_refresh import STATEMENTS_MARKER, refresh_statement_totals

    card = client.post("/api/accounts", json={"name": "Karte", "account_type": "credit_card"}).json()["id"]
    giro = client.post("/api/accounts", json={"name": "Giro", "account_type": "checking"}).json()["id"]
    path = _invoice(tmp_path, "rechnung.pdf", previous="80,00", payments="-80,00", total="60,00")
    preview = client.post("/api/imports/preview", data={"account_id": card},
                          files={"file": ("rechnung.pdf", io.BytesIO(path.read_bytes()), "application/pdf")}).json()
    assert client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": card}).status_code == 200
    with session_scope() as session:  # as an older reader stored it: the previous period's amount
        statement = session.exec(select(CreditCardStatement)).one()
        statement.statement_total_minor = 8000
        session.add(statement)
        session.commit()
    # the previous bill (paid in on the statement as "Payment") and this one
    body = (b"Datum,Beschreibung,Betrag\n2026-09-30,Lastschrift BEISPIELBANK KARTE,-80.00\n"
            b"2026-10-30,Lastschrift BEISPIELBANK KARTE,-60.00\n")
    preview = client.post("/api/imports/preview", data={"account_id": giro},
                          files={"file": ("giro.csv", io.BytesIO(body), "text/csv")}).json()
    assert client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": giro}).status_code == 200

    (settings.data_dir / STATEMENTS_MARKER).unlink(missing_ok=True)
    with session_scope() as session:
        assert refresh_statement_totals(session) == 1
        assert refresh_statement_totals(session) == 0  # once per version
    [statement] = client.get(f"/api/credit-cards/{card}/statements").json()
    assert statement["statement_total_minor"] == 6000
    assert statement["reconciliation_status"] == "reconciled"


def test_a_card_debit_on_a_late_due_date_is_linked(client, tmp_path):
    """Bank Norwegian debits on the due date, 15 days after the statement
    date (later at weekends): still the statement's payment, not an expense."""
    card = client.post("/api/accounts", json={"name": "Karte", "account_type": "credit_card"}).json()["id"]
    giro = client.post("/api/accounts", json={"name": "Giro", "account_type": "checking"}).json()["id"]
    body = (b"Datum,Beschreibung,Betrag\n2026-09-30,Lastschrift BEISPIELBANK KARTE,-80.00\n"
            b"2026-11-02,Lastschrift BEISPIELBANK KARTE,-60.00\n")  # 18 days after the period's end
    preview = client.post("/api/imports/preview", data={"account_id": giro},
                          files={"file": ("giro.csv", io.BytesIO(body), "text/csv")}).json()
    client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": giro})
    path = _invoice(tmp_path, "rechnung.pdf", previous="80,00", payments="-80,00", total="60,00")
    preview = client.post("/api/imports/preview", data={"account_id": card},
                          files={"file": ("rechnung.pdf", io.BytesIO(path.read_bytes()), "application/pdf")}).json()
    client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": card})
    [statement] = client.get(f"/api/credit-cards/{card}/statements").json()
    assert statement["reconciliation_status"] == "reconciled"
    debit = next(t for t in client.get("/api/transactions", params={"account_id": giro}).json()["items"]
                 if t["amount_minor"] == -6000)
    assert debit["is_transfer"]  # not counted as an expense on top of the card's purchases
