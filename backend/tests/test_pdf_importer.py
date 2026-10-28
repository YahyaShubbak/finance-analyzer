from app.db.models import DocumentType
from app.importers.pdf_importer import PDFImporter
from tests.pdf_fixtures import write_blank_pdf, write_text_pdf


def test_generic_bank_statement_pdf_parsed(tmp_path):
    pdf_path = write_text_pdf(tmp_path / "bank.pdf", [
        "Bank Statement",
        "Checking Account - IBAN DE00 1234 5678 9012 3456 78",
        "Statement Period: 01.03.2026 - 31.03.2026",
        "",
        "01.03.2026 Lidl Supermarket -32.40 EUR",
        "05.03.2026 Salary 2500.00 EUR",
        "15.03.2026 Credit Card Payment -342.37 EUR",
    ])

    result = PDFImporter(pdf_path).parse()

    assert not result.has_errors
    assert not result.ambiguous
    assert result.document_type == DocumentType.BANK_STATEMENT
    assert result.detected_layout == "generic_bank_statement_v1"
    assert len(result.transactions) == 3
    assert result.period_start == "2026-03-01"
    assert result.period_end == "2026-03-31"

    lidl = result.transactions[0]
    assert lidl.parsed_amount_minor == -3240


def test_generic_credit_card_statement_pdf_parsed(tmp_path):
    pdf_path = write_text_pdf(tmp_path / "cc.pdf", [
        "Credit Card Statement",
        "VISA ending 1234",
        "Statement Period: 01.03.2026 - 31.03.2026",
        "",
        "02.03.2026 Amazon.de 129.99 EUR",
        "05.03.2026 Netflix.com 17.99 EUR",
        "10.03.2026 REWE Supermarket 194.39 EUR",
        "",
        "Statement Total: 342.37 EUR",
    ])

    result = PDFImporter(pdf_path).parse()

    assert not result.has_errors
    assert result.document_type == DocumentType.CREDIT_CARD_STATEMENT
    assert result.detected_layout == "generic_credit_card_statement_v1"
    assert len(result.transactions) == 3
    assert result.statement_total_minor == 34237

    # Charges are stored as negative (expense convention), even though the
    # statement itself lists them as positive magnitudes.
    amazon = result.transactions[0]
    assert amazon.parsed_amount_minor == -12999


def test_credit_card_statement_with_refund_line(tmp_path):
    pdf_path = write_text_pdf(tmp_path / "cc_refund.pdf", [
        "Credit Card Statement",
        "VISA ending 1234",
        "Statement Period: 01.03.2026 - 31.03.2026",
        "02.03.2026 Amazon.de 200.00 EUR",
        "08.03.2026 Amazon.de Refund -50.00 EUR",
        "10.03.2026 REWE Supermarket 100.00 EUR",
        "Statement Total: 250.00 EUR",
    ])

    result = PDFImporter(pdf_path).parse()

    refund = result.transactions[1]
    # Statement shows the refund as a negative (credit); internal convention
    # inverts CC amounts, so a credit becomes a positive DB value.
    assert refund.parsed_amount_minor == 5000
    assert result.statement_total_minor == 25000


def test_blank_pdf_fails_safely_no_guessing(tmp_path):
    pdf_path = write_blank_pdf(tmp_path / "blank.pdf")
    result = PDFImporter(pdf_path).parse()

    assert result.has_errors
    assert result.ambiguous
    assert result.transactions == []
    assert result.document_type == DocumentType.UNKNOWN


def test_unrecognized_layout_fails_safely(tmp_path):
    pdf_path = write_text_pdf(tmp_path / "mystery.pdf", [
        "Some random cover letter",
        "This document does not look like a bank or credit-card statement at all.",
        "Thank you for your business.",
    ])
    result = PDFImporter(pdf_path).parse()

    assert result.ambiguous
    assert result.transactions == []
    assert any("Could not confidently identify" in i.message for i in result.issues)


def test_corrupt_pdf_fails_safely(tmp_path):
    bad_pdf = tmp_path / "corrupt.pdf"
    bad_pdf.write_bytes(b"%PDF-1.4 this is not a real pdf structure at all")

    result = PDFImporter(bad_pdf).parse()

    assert result.has_errors
    assert result.ambiguous
    assert result.transactions == []


def test_pdf_checksum_stable():
    import tempfile
    from pathlib import Path

    from tests.pdf_fixtures import write_text_pdf

    with tempfile.TemporaryDirectory() as d:
        p1 = write_text_pdf(Path(d) / "a.pdf", ["Bank Statement", "Kontoauszug",
                                                  "01.01.2026 Test -10.00 EUR"])
        r1 = PDFImporter(p1).parse()
        r2 = PDFImporter(p1).parse()
        assert r1.file_checksum == r2.file_checksum
