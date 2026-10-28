from __future__ import annotations

from datetime import date

from app.db.models import DocumentType, ImportRecord, ImportStatus, RawTransaction, Transaction, TransactionType
from app.importers.base import ParsedTransaction
from app.services.duplicate_detection import compute_duplicate_fingerprint
from app.services.duplicate_preview_service import classify_import_rows


def _seed_existing_transaction(
    session, account_id, day, amount_minor, description, merchant=None
) -> Transaction:
    imp = ImportRecord(
        filename=f"seed_{day}.csv", stored_path="x", file_checksum=f"chk{day}{amount_minor}{description}",
        document_type=DocumentType.BANK_STATEMENT, account_id=account_id, status=ImportStatus.IMPORTED,
    )
    session.add(imp)
    session.commit()
    session.refresh(imp)

    raw = RawTransaction(import_id=imp.id, source_row_index=0, original_description=description)
    session.add(raw)
    session.commit()
    session.refresh(raw)

    tx = Transaction(
        raw_transaction_id=raw.id,
        account_id=account_id,
        transaction_date=date(2026, 3, day),
        normalized_description=description,
        merchant=merchant,
        amount_minor=amount_minor,
        currency="EUR",
        transaction_type=TransactionType.EXPENSE if amount_minor < 0 else TransactionType.INCOME,
        duplicate_fingerprint=compute_duplicate_fingerprint(account_id, f"2026-03-{day:02d}", amount_minor, description),
    )
    session.add(tx)
    session.commit()
    session.refresh(tx)
    return tx


def _ptx(row, date_iso, amount_minor, description):
    return ParsedTransaction(
        source_row_index=row,
        original_date_text=date_iso,
        original_description=description,
        original_amount_text=str(amount_minor / 100),
        parsed_date=date_iso,
        parsed_amount_minor=amount_minor,
    )


def test_new_transaction_no_match(session, checking_account):
    results = classify_import_rows(session, checking_account.id, [_ptx(0, "2026-03-01", -1000, "Coffee Shop")])
    assert results[0].status == "new"
    assert results[0].match is None


def test_exact_duplicate_detected(session, checking_account):
    _seed_existing_transaction(session, checking_account.id, 1, -4567, "REWE SAGT DANKE 12345", merchant="REWE")

    results = classify_import_rows(
        session, checking_account.id, [_ptx(0, "2026-03-01", -4567, "REWE SAGT DANKE 12345")]
    )
    assert results[0].status == "exact_duplicate"
    assert results[0].match is not None
    assert "existing transaction" in results[0].match_reason.lower()


def test_possible_duplicate_requires_all_three_signals(session, checking_account):
    _seed_existing_transaction(session, checking_account.id, 1, -1999, "Netflix.com", merchant="Netflix")

    # Same merchant + same amount + 1 day apart -> possible duplicate.
    results = classify_import_rows(
        session, checking_account.id, [_ptx(0, "2026-03-02", -1999, "NETFLIX.COM SUBSCRIPTION")]
    )
    assert results[0].status == "possible_duplicate"
    assert results[0].match.id is not None
    assert "same merchant" in results[0].match_reason.lower()
    assert "same amount" in results[0].match_reason.lower()
    assert "1 day" in results[0].match_reason


def test_same_amount_and_nearby_date_alone_not_flagged(session, checking_account):
    """Two signals only (amount + date, no merchant match) must NOT be
    flagged — the conservative requirement from the spec."""
    _seed_existing_transaction(session, checking_account.id, 1, -1999, "Netflix.com", merchant="Netflix")

    results = classify_import_rows(
        session, checking_account.id, [_ptx(0, "2026-03-02", -1999, "Some Unrelated Merchant")]
    )
    assert results[0].status == "new"


def test_same_merchant_and_nearby_date_alone_not_flagged(session, checking_account):
    """Two signals only (merchant + date, different amount) must NOT be
    flagged."""
    _seed_existing_transaction(session, checking_account.id, 1, -1999, "Netflix.com", merchant="Netflix")

    results = classify_import_rows(
        session, checking_account.id, [_ptx(0, "2026-03-02", -2999, "Netflix.com")]
    )
    assert results[0].status == "new"


def test_recurring_subscription_far_apart_in_time_not_flagged(session, checking_account):
    """Same merchant + same amount but a month apart (a normal recurring
    charge) must not be treated as a duplicate — date proximity is
    required, not optional."""
    _seed_existing_transaction(session, checking_account.id, 1, -1999, "Netflix.com", merchant="Netflix")

    results = classify_import_rows(
        session, checking_account.id,
        [_ptx(0, "2026-04-01", -1999, "Netflix.com")],  # ~1 month later
    )
    assert results[0].status == "new"


def test_date_exactly_at_window_boundary_flagged(session, checking_account):
    _seed_existing_transaction(session, checking_account.id, 1, -500, "Coffee Shop", merchant="Coffee Shop")

    results = classify_import_rows(
        session, checking_account.id, [_ptx(0, "2026-03-03", -500, "Coffee Shop")]  # exactly 2 days
    )
    assert results[0].status == "possible_duplicate"


def test_date_just_outside_window_not_flagged(session, checking_account):
    _seed_existing_transaction(session, checking_account.id, 1, -500, "Coffee Shop", merchant="Coffee Shop")

    results = classify_import_rows(
        session, checking_account.id, [_ptx(0, "2026-03-04", -500, "Coffee Shop")]  # 3 days
    )
    assert results[0].status == "new"


def test_duplicate_of_transaction_in_different_account_not_flagged(session, checking_account, savings_account):
    _seed_existing_transaction(session, savings_account.id, 1, -1999, "Netflix.com", merchant="Netflix")

    results = classify_import_rows(
        session, checking_account.id, [_ptx(0, "2026-03-01", -1999, "Netflix.com")]
    )
    assert results[0].status == "new"


def test_exact_duplicate_takes_priority_over_possible(session, checking_account):
    """A row that matches exactly should be classified as exact, not
    possible, even though it would also satisfy the possible-duplicate
    signals."""
    _seed_existing_transaction(session, checking_account.id, 1, -1999, "Netflix.com", merchant="Netflix")

    results = classify_import_rows(
        session, checking_account.id, [_ptx(0, "2026-03-01", -1999, "Netflix.com")]
    )
    assert results[0].status == "exact_duplicate"


def test_new_row_includes_category_and_needs_review(session, checking_account):
    results = classify_import_rows(
        session, checking_account.id, [_ptx(0, "2026-03-01", -5000, "Amazon.de")]
    )
    assert results[0].status == "new"
    assert results[0].parsed_merchant == "Amazon"
    assert results[0].parsed_category == "Shopping"
    assert results[0].needs_review is False


def test_unclassifiable_new_row_flagged_needs_review(session, checking_account):
    results = classify_import_rows(
        session, checking_account.id, [_ptx(0, "2026-03-01", -1234, "XYZ Totally Unknown Vendor 998877")]
    )
    assert results[0].status == "new"
    assert results[0].needs_review is True
    assert results[0].review_reason is not None


def test_duplicate_rows_never_flagged_needs_review(session, checking_account):
    """Duplicates are resolved via keep/skip, not the review queue — even
    if the merchant/category would otherwise be unclear."""
    _seed_existing_transaction(session, checking_account.id, 1, -1234, "XYZ Totally Unknown Vendor 998877")

    results = classify_import_rows(
        session, checking_account.id, [_ptx(0, "2026-03-01", -1234, "XYZ Totally Unknown Vendor 998877")]
    )
    assert results[0].status == "exact_duplicate"
    assert results[0].needs_review is False
    _seed_existing_transaction(session, checking_account.id, 1, -1999, "Netflix.com", merchant="Netflix")

    results = classify_import_rows(
        session, checking_account.id,
        [
            _ptx(0, "2026-03-01", -1999, "Netflix.com"),          # exact
            _ptx(1, "2026-03-02", -1999, "NETFLIX.COM SUB"),      # possible (1 day gap, merchant normalizes to Netflix)
            _ptx(2, "2026-03-15", -5000, "Amazon.de"),            # new
        ],
    )
    statuses = {r.source_row_index: r.status for r in results}
    assert statuses[0] == "exact_duplicate"
    assert statuses[1] == "possible_duplicate"
    assert statuses[2] == "new"
