"""Statements printed as a table (the comdirect layout), rebuilt from their
STRUCTURE with invented content: a two-row header, bookings as blocks of
rows (booking date / value date, booking type, payee / IBAN, purpose with
SEPA references), the signed amount flush right in its own column — and a
number in the purpose text right before it."""
from __future__ import annotations

import io

from app.importers.pdf_importer import PDFImporter
from tests.pdf_fixtures import write_table_pdf

DATE, TYPE, PARTY, TEXT, AMOUNT = 60, 118, 189, 309, 553


def _block(rows):
    return [[(x, text, "r" if x == AMOUNT else "l") for x, text in row] for row in rows]


ROWS = [
    [(57, "Kontoauszug Nr. 3 per 01.04.2026", "l")],
    [(57, "Zeitraum: 01.03.2026 - 31.03.2026", "l")],
    [],
    [(DATE, "Buchungstag", "l"), (TYPE, "Vorgang", "l"), (PARTY, "Auftraggeber/Empfänger", "l"),
     (TEXT, "Buchungstext", "l"), (AMOUNT, "Ausgang", "r")],
    [(DATE, "Valuta", "l"), (TYPE, "Referenz", "l"), (PARTY, "IBAN/BIC", "l"), (AMOUNT, "Eingang", "r")],
    [(DATE, "Alter Saldo 28.02.2026", "l"), (AMOUNT, "+1.000,00", "r")],
    *_block([
        [(DATE, "06.03.2026"), (TYPE, "Lastschrift /"), (PARTY, "BEISPIEL VERSICHERUNG"),
         (TEXT, "12345-004 KS PA 27 737,84"), (AMOUNT, "-737,84")],
        [(DATE, "06.03.2026"), (TYPE, "Belastung"), (TEXT, "Beispieltarif")],
        [(TYPE, "AB12CD34"), (TEXT, "End-to-End-Ref.:")],
        [(TEXT, "20260303-12345004")],
        [(TEXT, "Gläubiger-ID:")],
        [(TEXT, "DE98ZZZ00000012345")],
    ]),
    *_block([
        [(DATE, "10.03.2026"), (TYPE, "Übertrag /"), (PARTY, "Max Muster"), (TEXT, "End-to-End-Ref.:"),
         (AMOUNT, "-300,00")],
        [(DATE, "10.03.2026"), (TYPE, "Überweisung"), (TEXT, "nicht angegeben")],
        [(TYPE, "HF2250"), (PARTY, "DE89370400440532013000")],
        [(PARTY, "COBADEFFXXX")],
    ]),
    [(57, "Beispielbank – eine Marke der Beispiel AG USt-ID: DE 123 456 789", "l")],
    *_block([
        [(DATE, "15.03.2026"), (TYPE, "Übertrag /"), (PARTY, "Arbeitgeber AG"), (TEXT, "Gehalt Maerz"),
         (AMOUNT, "+2.000,00")],
        [(DATE, "15.03.2026"), (TYPE, "Gutschrift")],
    ]),
    [(DATE, "Neuer Saldo 31.03.2026", "l"), (AMOUNT, "+1.962,16", "r")],
]


def test_table_statement_is_read_by_column(tmp_path):
    result = PDFImporter(write_table_pdf(tmp_path / "statement.pdf", ROWS, line_height=10)).parse()

    tx = result.transactions
    assert [t.parsed_amount_minor for t in tx] == [-73784, -30000, 200000]   # not 27 737,84
    assert result.total_check == {"kind": "balance", "ok": True, "difference_minor": 0}
    assert tx[0].counterparty == "BEISPIEL VERSICHERUNG"
    assert "27 737,84" in tx[0].original_description                       # the number stays text
    assert "End-to-End-Ref.: 20260303-12345004" in tx[0].extra_fields["_details"]
    assert tx[0].extra_fields["_value_date"] == "2026-03-06"
    assert tx[1].counterparty == "Max Muster"
    assert tx[1].counterparty_iban == "DE89370400440532013000"
    assert tx[2].counterparty == "Arbeitgeber AG"


def test_table_payee_becomes_the_merchant(client, tmp_path):
    account = client.post("/api/accounts", json={"name": "Giro", "account_type": "checking"}).json()["id"]
    pdf = write_table_pdf(tmp_path / "statement.pdf", ROWS, line_height=10)
    preview = client.post("/api/imports/preview", files={"file": ("s.pdf", io.BytesIO(pdf.read_bytes()), "application/pdf")},
                          data={"account_id": account}).json()
    assert preview["total_check"]["ok"]
    client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": account})
    merchants = {t["amount_minor"]: t["merchant"] for t in client.get("/api/transactions").json()["items"]}
    assert merchants[-73784] == "BEISPIEL VERSICHERUNG"
    assert merchants[200000] == "Arbeitgeber AG"
