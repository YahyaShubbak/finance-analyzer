"""Service-level tests for recurring_service.get_forecast, built directly
against the session/model fixtures (like test_money_and_models.py) rather
than through the HTTP API — this lets tests pin `as_of` explicitly instead
of depending on the real wall-clock date.
"""
from __future__ import annotations

from datetime import date

from app.db.models import DocumentType, ImportRecord, ImportStatus, RawTransaction, Transaction, TransactionType
from app.services.duplicate_detection import compute_duplicate_fingerprint
from app.services.recurring_service import get_forecast


def _fake_import(session, account_id: int) -> int:
    imp = ImportRecord(
        filename="test.csv", stored_path="imports/test.csv", file_checksum="deadbeef",
        document_type=DocumentType.BANK_STATEMENT, account_id=account_id, status=ImportStatus.IMPORTED,
    )
    session.add(imp)
    session.commit()
    session.refresh(imp)
    return imp.id


def _add_transaction(session, account_id: int, tx_date: date, amount_minor: int, description: str):
    raw = RawTransaction(
        import_id=_fake_import(session, account_id), source_row_index=0,
        original_amount_text=str(amount_minor / 100), original_description=description,
        original_date_text=tx_date.isoformat(),
    )
    session.add(raw)
    session.commit()
    session.refresh(raw)

    tx = Transaction(
        raw_transaction_id=raw.id, account_id=account_id, transaction_date=tx_date,
        normalized_description=description, merchant=description, amount_minor=amount_minor, currency="EUR",
        transaction_type=TransactionType.INCOME if amount_minor > 0 else TransactionType.EXPENSE,
        duplicate_fingerprint=compute_duplicate_fingerprint(account_id, tx_date.isoformat(), amount_minor, description),
    )
    session.add(tx)
    session.commit()


def test_forecast_last_month_not_truncated_by_day_of_month(session, checking_account):
    """Regression guard: the forecast horizon must cover full calendar
    months, not "as_of + N months" as a fixed day-of-month — a monthly
    series whose last real occurrence lands late in a month (the 28th)
    must still contribute a projected occurrence to the third forecasted
    month when as_of is early in its own month (the 2nd)."""
    for tx_date in [date(2026, 5, 28), date(2026, 6, 28), date(2026, 7, 28), date(2026, 8, 28)]:
        _add_transaction(session, checking_account.id, tx_date, -90000, "Rent")

    result = get_forecast(session, months=3, as_of=date(2026, 9, 2))

    assert [p.month for p in result.points] == ["2026-10", "2026-11", "2026-12"]
    for point in result.points:
        assert point.recurring_net_minor == -90000, point


def test_monthly_series_projects_exactly_once_per_month(session, checking_account):
    """A fixed 30-day step from 1 Sep lands on 1 Oct AND 31 Oct — the
    forecast must step in calendar months instead."""
    for tx_date in [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1)]:
        _add_transaction(session, checking_account.id, tx_date, -1299, "Netflix")

    result = get_forecast(session, months=3, as_of=date(2026, 9, 15))

    assert [(p.month, p.recurring_net_minor) for p in result.points] == [
        ("2026-10", -1299), ("2026-11", -1299), ("2026-12", -1299),
    ]


def test_cancelled_subscription_is_not_forecast(session, checking_account):
    for tx_date in [date(2025, 2, 5), date(2025, 3, 5), date(2025, 4, 5), date(2025, 5, 5)]:
        _add_transaction(session, checking_account.id, tx_date, -999, "Old Streaming")

    result = get_forecast(session, months=3, as_of=date(2026, 9, 15))

    assert result.series_count == 0
    assert all(p.recurring_net_minor == 0 for p in result.points)
