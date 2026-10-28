from pathlib import Path

from app.importers.csv_importer import CSVImporter

FIXTURES = Path(__file__).parent / "fixtures"


def test_german_semicolon_decimal_comma():
    importer = CSVImporter(FIXTURES / "checking_january_de.csv")
    result = importer.parse()

    assert not result.has_errors
    assert not result.ambiguous
    assert len(result.transactions) == 5

    rewe = result.transactions[0]
    assert rewe.original_description == "REWE SAGT DANKE 12345"
    assert rewe.parsed_amount_minor == -4567
    assert rewe.parsed_date == "2026-01-02"

    salary = result.transactions[1]
    assert salary.parsed_amount_minor == 250000


def test_us_comma_decimal_point():
    importer = CSVImporter(FIXTURES / "checking_february_us.csv")
    result = importer.parse()

    assert not result.has_errors
    assert len(result.transactions) == 5
    assert result.transactions[0].parsed_amount_minor == -450
    assert result.period_start == "2026-02-01"
    assert result.period_end == "2026-02-20"


def test_debit_credit_columns_combined_into_signed_amount():
    importer = CSVImporter(FIXTURES / "checking_debit_credit.csv")
    result = importer.parse()

    assert not result.has_errors
    lidl, salary, transfer = result.transactions
    assert lidl.parsed_amount_minor == -3240
    assert salary.parsed_amount_minor == 250000
    assert transfer.parsed_amount_minor == -50000


def test_ambiguous_file_is_flagged_not_guessed(tmp_path):
    bad_csv = tmp_path / "mystery.csv"
    bad_csv.write_text("Col1,Col2,Col3\nfoo,bar,baz\n", encoding="utf-8")

    importer = CSVImporter(bad_csv)
    result = importer.parse()

    assert result.ambiguous


def test_checksum_is_stable_and_content_based(tmp_path):
    f1 = tmp_path / "a.csv"
    f2 = tmp_path / "b.csv"
    f1.write_text("Date,Description,Amount\n2026-01-01,Test,-10.00\n")
    f2.write_text("Date,Description,Amount\n2026-01-01,Test,-10.00\n")

    r1 = CSVImporter(f1).parse()
    r2 = CSVImporter(f2).parse()
    assert r1.file_checksum == r2.file_checksum  # identical content -> identical checksum


def test_encoding_tolerance_latin1(tmp_path):
    # "Café" encoded as latin-1 (contains a byte that's invalid utf-8)
    f = tmp_path / "latin1.csv"
    content = "Date,Description,Amount\n2026-01-01,Café Müller,-5,50\n"
    f.write_bytes(content.encode("latin-1"))

    result = CSVImporter(f).parse()
    assert not result.has_errors
    assert "Café Müller" in result.transactions[0].original_description
