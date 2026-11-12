from pathlib import Path

import pytest
from sqlmodel import select

from app.db.models import ImportRecord, RawTransaction, Transaction
from app.services.import_service import ImportServiceError, commit_parsed_import, parse_file

FIXTURES = Path(__file__).parent / "fixtures"


def test_commit_parsed_import_persists_raw_and_normalized(session, checking_account):
    parsed = parse_file(FIXTURES / "checking_january_de.csv")
    result = commit_parsed_import(
        session, parsed, account_id=checking_account.id, stored_path="imports/checking_january_de.csv"
    )

    assert result.transactions_created == 5
    assert result.duplicates_flagged == 0

    raws = session.exec(select(RawTransaction)).all()
    txs = session.exec(select(Transaction)).all()
    assert len(raws) == 5
    assert len(txs) == 5

    # Original text preserved verbatim
    rewe_raw = next(r for r in raws if "REWE" in (r.original_description or ""))
    assert rewe_raw.original_amount_text == "-45,67"

    # Normalization applied
    amazon_tx = next(t for t in txs if t.merchant == "Amazon")
    assert amazon_tx.amount_minor == -12999
    assert amazon_tx.category == "Shopping"

    netflix_tx = next(t for t in txs if t.merchant == "Netflix")
    assert netflix_tx.category == "Subscriptions"

    salary_tx = next(t for t in txs if t.amount_minor == 250000)
    assert salary_tx.category == "Salary"
    assert salary_tx.transaction_type.value == "income"


def test_raw_transaction_traces_back_to_import(session, checking_account):
    parsed = parse_file(FIXTURES / "checking_january_de.csv")
    commit_parsed_import(session, parsed, checking_account.id, "imports/x.csv")

    tx = session.exec(select(Transaction)).first()
    raw = session.get(RawTransaction, tx.raw_transaction_id)
    import_record = session.get(ImportRecord, raw.import_id)

    assert import_record.filename == "checking_january_de.csv"
    assert import_record.status.value == "imported"


def test_reimporting_identical_file_is_rejected(session, checking_account):
    parsed = parse_file(FIXTURES / "checking_january_de.csv")
    commit_parsed_import(session, parsed, checking_account.id, "imports/x.csv")

    parsed_again = parse_file(FIXTURES / "checking_january_de.csv")
    with pytest.raises(ImportServiceError, match="already been imported"):
        commit_parsed_import(session, parsed_again, checking_account.id, "imports/x_copy.csv")

    # No duplicate transactions were created
    assert len(session.exec(select(Transaction)).all()) == 5


def test_cross_file_duplicate_transaction_is_skipped_by_default_not_duplicated(session, checking_account, tmp_path):
    """An exact-fingerprint duplicate arriving via a different file
    defaults to being skipped (spec Milestone 3: exact duplicates default
    to "skip", excluded from totals) rather than imported as a second,
    merely-flagged transaction. The raw row is still preserved for
    auditability even though no Transaction is created for it."""
    f1 = tmp_path / "jan_v1.csv"
    f1.write_text(
        "Date,Description,Amount\n2026-01-02,REWE SAGT DANKE 12345,-45.67\n", encoding="utf-8"
    )
    f2 = tmp_path / "jan_v2.csv"
    f2.write_text(
        "Date,Description,Amount\n"
        "2026-01-02,REWE SAGT DANKE 12345,-45.67\n"
        "2026-01-03,New Unique Transaction,-10.00\n",
        encoding="utf-8",
    )

    commit_parsed_import(session, parse_file(f1), checking_account.id, "imports/jan_v1.csv")
    result2 = commit_parsed_import(session, parse_file(f2), checking_account.id, "imports/jan_v2.csv")

    assert result2.transactions_created == 1  # only the new unique one
    assert result2.duplicates_flagged == 1
    assert result2.rows_skipped == 1

    txs = session.exec(select(Transaction)).all()
    assert len(txs) == 2  # the duplicate row was skipped, not imported as a flagged duplicate

    # But the raw row is still preserved for traceability, even without a
    # Transaction — original source data is never discarded.
    raws = session.exec(select(RawTransaction)).all()
    assert len(raws) == 3
    assert any(r.original_description == "REWE SAGT DANKE 12345" for r in raws)


def test_row_decision_keep_imports_exact_duplicate_as_legitimate_transaction(session, checking_account, tmp_path):
    """The user can explicitly override the default and keep what would
    otherwise be an exact-fingerprint duplicate (e.g. two genuinely
    identical same-day purchases)."""
    f1 = tmp_path / "a.csv"
    f1.write_text("Date,Description,Amount\n2026-01-02,Coffee Shop,-4.50\n", encoding="utf-8")
    f2 = tmp_path / "b.csv"
    f2.write_text(
        "Date,Description,Amount\n2026-01-02,Coffee Shop,-4.50\n2026-01-03,Unrelated Row,-1.00\n",
        encoding="utf-8",
    )

    commit_parsed_import(session, parse_file(f1), checking_account.id, "imports/a.csv")
    result2 = commit_parsed_import(
        session, parse_file(f2), checking_account.id, "imports/b.csv",
        row_decisions={0: "keep"},
    )

    assert result2.transactions_created == 2  # the kept duplicate + the unrelated row
    assert result2.rows_skipped == 0

    txs = session.exec(select(Transaction)).all()
    assert len(txs) == 3
    assert all(not t.is_duplicate for t in txs)  # all are genuine, non-duplicate-flagged transactions


def test_a_long_file_is_stored_in_a_few_writes_and_every_booking_keeps_its_row(session, checking_account, tmp_path):
    """One flush per row made a year's export thousands of round trips to the
    database. Written together, each booking must still belong to exactly
    the raw row it was read from — also next to a row that gets no booking."""
    from sqlalchemy import event

    rows = [f"2026-01-{day % 28 + 1:02d},Shop number {day},-{day}.50" for day in range(1, 201)]
    rows.insert(100, "2026-01-15,A row without an amount,")
    path = tmp_path / "year.csv"
    path.write_text("Date,Description,Amount\n" + "\n".join(rows) + "\n", encoding="utf-8")
    parsed = parse_file(path)

    flushes = []
    event.listen(session, "after_flush", lambda *_: flushes.append(1))
    result = commit_parsed_import(session, parsed, checking_account.id, "imports/year.csv")

    assert result.transactions_created == 200
    assert len(flushes) < 20  # not one per row

    raws = {r.id: r for r in session.exec(select(RawTransaction)).all()}
    assert len(raws) == 201 and sorted(r.source_row_index for r in raws.values()) == list(range(201))
    txs = session.exec(select(Transaction)).all()
    assert len({t.raw_transaction_id for t in txs}) == 200
    for tx in txs:
        raw = raws[tx.raw_transaction_id]
        assert raw.original_description == tx.normalized_description
        assert raw.original_amount_text == f"{tx.amount_minor / 100:.2f}"
    assert not any(raws[t.raw_transaction_id].original_description == "A row without an amount" for t in txs)
