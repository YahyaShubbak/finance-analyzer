from __future__ import annotations

from datetime import date

from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import Account, AccountType, Transaction
from app.importers.xlsx_importer import XLSXImporter
from app.services.import_service import ImportServiceError, commit_parsed_import, parse_file
from tests.xlsx_fixtures import write_xlsx


def test_normal_xlsx_import_native_typed_cells(tmp_path):
    path = write_xlsx(
        tmp_path / "checking.xlsx",
        ["Date", "Description", "Amount", "Currency"],
        [
            [date(2026, 4, 1), "Lidl Supermarket", -32.40, "EUR"],
            [date(2026, 4, 5), "Salary", 2500.00, "EUR"],
        ],
    )

    result = XLSXImporter(path).parse()

    assert not result.has_errors
    assert not result.ambiguous
    assert len(result.transactions) == 2
    assert result.transactions[0].parsed_amount_minor == -3240
    assert result.transactions[0].parsed_date == "2026-04-01"
    assert result.transactions[1].parsed_amount_minor == 250000
    assert result.period_start == "2026-04-01"
    assert result.period_end == "2026-04-05"


def test_german_decimal_and_date_text_formatting(tmp_path):
    # Some exports store German-formatted values as plain text rather than
    # native Excel number/date types.
    path = write_xlsx(
        tmp_path / "german_text.xlsx",
        ["Buchungsdatum", "Verwendungszweck", "Betrag"],
        [
            ["02.04.2026", "REWE SAGT DANKE 12345", "-45,67"],
            ["05.04.2026", "AMZN MKTP DE*AB12CD3", "-129,99"],
        ],
    )

    result = XLSXImporter(path).parse()

    assert not result.has_errors
    assert result.transactions[0].parsed_date == "2026-04-02"
    assert result.transactions[0].parsed_amount_minor == -4567
    assert result.transactions[1].parsed_amount_minor == -12999


def test_debit_credit_columns_xlsx(tmp_path):
    path = write_xlsx(
        tmp_path / "debit_credit.xlsx",
        ["Booking Date", "Description", "Debit", "Credit"],
        [
            [date(2026, 4, 1), "Lidl Supermarket", 32.40, None],
            [date(2026, 4, 5), "Salary", None, 2500.00],
        ],
    )

    result = XLSXImporter(path).parse()

    assert not result.has_errors
    assert result.transactions[0].parsed_amount_minor == -3240
    assert result.transactions[1].parsed_amount_minor == 250000


def test_duplicate_xlsx_file_rejected(session, checking_account, tmp_path):
    path = write_xlsx(
        tmp_path / "april.xlsx",
        ["Date", "Description", "Amount"],
        [[date(2026, 4, 1), "Lidl Supermarket", -32.40]],
    )

    parsed = parse_file(path)
    commit_parsed_import(session, parsed, checking_account.id, "imports/april.xlsx")

    parsed_again = parse_file(path)
    import pytest
    with pytest.raises(ImportServiceError, match="already been imported"):
        commit_parsed_import(session, parsed_again, checking_account.id, "imports/april_copy.xlsx")

    assert len(session.exec(select(Transaction)).all()) == 1


def test_xlsx_ambiguous_when_columns_unrecognized(tmp_path):
    path = write_xlsx(
        tmp_path / "mystery.xlsx",
        ["Col1", "Col2", "Col3"],
        [["foo", "bar", "baz"]],
    )
    result = XLSXImporter(path).parse()
    assert result.ambiguous


def test_xlsx_persistence_across_restart(tmp_path):
    """Same multi-session guarantee as CSV/PDF (spec section 41), for xlsx."""
    db_path = tmp_path / "finance.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    april = write_xlsx(
        tmp_path / "april.xlsx",
        ["Date", "Description", "Amount"],
        [
            [date(2026, 4, 1), "Lidl Supermarket", -32.40],
            [date(2026, 4, 5), "Salary", 2500.00],
        ],
    )
    may = write_xlsx(
        tmp_path / "may.xlsx",
        ["Date", "Description", "Amount"],
        [[date(2026, 5, 3), "Rent May", -950.00]],
    )

    # Session 1
    with Session(engine) as s:
        acc = Account(name="Checking Account", account_type=AccountType.CHECKING, currency="EUR")
        s.add(acc)
        s.commit()
        s.refresh(acc)
        acc_id = acc.id
        commit_parsed_import(s, parse_file(april), acc_id, "imports/april.xlsx")
        assert len(s.exec(select(Transaction)).all()) == 2

    # "Restart": brand-new engine/session against the same file.
    engine2 = create_engine(f"sqlite:///{db_path}")
    with Session(engine2) as s:
        assert len(s.exec(select(Transaction)).all()) == 2  # still there

        commit_parsed_import(s, parse_file(may), acc_id, "imports/may.xlsx")
        assert len(s.exec(select(Transaction)).all()) == 3

        # Re-importing April must not duplicate data.
        import pytest
        with pytest.raises(ImportServiceError, match="already been imported"):
            commit_parsed_import(s, parse_file(april), acc_id, "imports/april_again.xlsx")
        assert len(s.exec(select(Transaction)).all()) == 3
