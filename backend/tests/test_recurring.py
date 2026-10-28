"""Pure unit tests for app.normalization.recurring — no DB, synthetic
candidates only. Mirrors the test_transfers.py split: algorithmic
correctness here, end-to-end pipeline behavior in test_recurring_api.py.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.normalization.recurring import (
    RecurringCandidate,
    detect_recurring_series,
    project_series_forward,
)


def _monthly_dates(start: date, count: int) -> list[date]:
    dates = [start]
    for _ in range(count - 1):
        d = dates[-1]
        month = d.month + 1
        year = d.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        dates.append(date(year, month, min(d.day, 28)))
    return dates


def test_monthly_series_detected():
    dates = _monthly_dates(date(2026, 1, 5), 5)
    candidates = [RecurringCandidate(id=i, key="netflix", date=d, amount_minor=-1299) for i, d in enumerate(dates)]
    series = detect_recurring_series(candidates)
    assert len(series) == 1
    assert series[0].interval == "monthly"
    assert series[0].sign == -1
    assert len(series[0].occurrences) == 5
    assert series[0].last_amount_minor == -1299


def test_weekly_series_detected():
    dates = [date(2026, 1, 5) + timedelta(weeks=i) for i in range(4)]
    candidates = [RecurringCandidate(id=i, key="gym", date=d, amount_minor=-500) for i, d in enumerate(dates)]
    series = detect_recurring_series(candidates)
    assert len(series) == 1
    assert series[0].interval == "weekly"


def test_quarterly_series_detected():
    dates = [date(2026, 1, 15), date(2026, 4, 16), date(2026, 7, 17), date(2026, 10, 16)]
    candidates = [RecurringCandidate(id=i, key="insurance", date=d, amount_minor=-15000) for i, d in enumerate(dates)]
    series = detect_recurring_series(candidates)
    assert len(series) == 1
    assert series[0].interval == "quarterly"


def test_yearly_series_detected():
    dates = [date(2023, 6, 1), date(2024, 6, 3), date(2025, 5, 30), date(2026, 6, 2)]
    candidates = [RecurringCandidate(id=i, key="domain renewal", date=d, amount_minor=-1200) for i, d in enumerate(dates)]
    series = detect_recurring_series(candidates)
    assert len(series) == 1
    assert series[0].interval == "yearly"


def test_fewer_than_three_occurrences_not_detected():
    dates = _monthly_dates(date(2026, 1, 5), 2)
    candidates = [RecurringCandidate(id=i, key="netflix", date=d, amount_minor=-1299) for i, d in enumerate(dates)]
    assert detect_recurring_series(candidates) == []


def test_irregular_one_off_purchases_not_detected():
    # Same merchant, but random dates and random amounts — a real pattern
    # of occasional, unrelated visits, not a subscription.
    dates = [date(2026, 1, 3), date(2026, 2, 20), date(2026, 3, 1), date(2026, 5, 14)]
    amounts = [-1250, -430, -2010, -899]
    candidates = [
        RecurringCandidate(id=i, key="corner shop", date=d, amount_minor=a)
        for i, (d, a) in enumerate(zip(dates, amounts))
    ]
    assert detect_recurring_series(candidates) == []


def test_gradual_price_increase_still_detected():
    dates = _monthly_dates(date(2026, 1, 5), 6)
    amounts = [-999, -999, -999, -1299, -1299, -1299]  # a mid-series price increase
    candidates = [
        RecurringCandidate(id=i, key="streaming", date=d, amount_minor=a)
        for i, (d, a) in enumerate(zip(dates, amounts))
    ]
    series = detect_recurring_series(candidates)
    assert len(series) == 1
    assert series[0].last_amount_minor == -1299


def test_wild_amount_jump_not_detected_despite_regular_dates():
    dates = _monthly_dates(date(2026, 1, 5), 5)
    amounts = [-1000, -1000, -1000, -9000, -1000]  # one wildly out-of-pattern amount
    candidates = [
        RecurringCandidate(id=i, key="something", date=d, amount_minor=a)
        for i, (d, a) in enumerate(zip(dates, amounts))
    ]
    assert detect_recurring_series(candidates) == []


def test_one_skipped_monthly_occurrence_still_detected():
    # Jan, Feb, (missed March), April, May -> one gap of ~2 months.
    dates = [date(2026, 1, 5), date(2026, 2, 5), date(2026, 4, 5), date(2026, 5, 5)]
    candidates = [RecurringCandidate(id=i, key="rent", date=d, amount_minor=-90000) for i, d in enumerate(dates)]
    series = detect_recurring_series(candidates)
    assert len(series) == 1
    assert series[0].interval == "monthly"


def test_gap_beyond_max_missed_multiple_not_detected():
    # A gap of ~5 months exceeds MAX_MISSED_MULTIPLE (3x nominal).
    dates = [date(2026, 1, 5), date(2026, 2, 5), date(2026, 7, 5), date(2026, 8, 5)]
    candidates = [RecurringCandidate(id=i, key="rent", date=d, amount_minor=-90000) for i, d in enumerate(dates)]
    assert detect_recurring_series(candidates) == []


def test_refund_forms_independent_series_from_charge():
    charge_dates = _monthly_dates(date(2026, 1, 5), 4)
    refund_dates = _monthly_dates(date(2026, 1, 10), 3)
    candidates = [
        RecurringCandidate(id=i, key="acme", date=d, amount_minor=-2000) for i, d in enumerate(charge_dates)
    ] + [
        RecurringCandidate(id=100 + i, key="acme", date=d, amount_minor=2000) for i, d in enumerate(refund_dates)
    ]
    series = detect_recurring_series(candidates)
    signs = sorted(s.sign for s in series)
    assert signs == [-1, 1]


def test_project_series_forward_uses_last_amount_not_average():
    dates = _monthly_dates(date(2026, 1, 5), 4)
    amounts = [-999, -999, -999, -1299]
    candidates = [
        RecurringCandidate(id=i, key="streaming", date=d, amount_minor=a)
        for i, (d, a) in enumerate(zip(dates, amounts))
    ]
    series = detect_recurring_series(candidates)[0]

    points = project_series_forward(series, horizon_end=date(2026, 7, 31))
    assert len(points) == 3
    assert all(p.amount_minor == -1299 for p in points)
    assert points[0].date == date(2026, 5, 5)


def test_project_series_forward_horizon_end_is_inclusive():
    """A projected occurrence landing exactly on horizon_end (the last
    day of the final forecasted month) must be included, not excluded —
    the caller is expected to pass the last day of the month, not some
    earlier fixed-day-of-month cutoff (see recurring_service.get_forecast,
    which computes horizon_end this way specifically to avoid truncating
    the final forecasted month)."""
    dates = _monthly_dates(date(2026, 1, 2), 4)  # last_date = 2026-04-02
    candidates = [RecurringCandidate(id=i, key="rent", date=d, amount_minor=-90000) for i, d in enumerate(dates)]
    series = detect_recurring_series(candidates)[0]

    points = project_series_forward(series, horizon_end=date(2026, 12, 31))
    december_points = [p for p in points if p.date.strftime("%Y-%m") == "2026-12"]
    assert len(december_points) == 1
