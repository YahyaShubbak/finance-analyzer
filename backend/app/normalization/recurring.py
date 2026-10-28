"""Recurring-transaction detection.

A recurring series is a group of transactions at the same merchant (or
description, if no merchant), all the same sign (income or expense), that
occur at a regular interval (weekly/monthly/quarterly/yearly, within
tolerance) with amounts that stay consistent from one occurrence to the
next. Detection is deterministic — no AI/LLM, consistent with the rest of
this app's normalization (see app.normalization.category).

Two things are deliberately checked against the PREVIOUS occurrence
rather than a single global reference:

* Amount consistency is chained (occurrence N compared to N-1, not to the
  series average) so a gradual, legitimate price increase (e.g. a
  subscription going from 9.99 to 12.99) still passes even though the
  first and last amounts differ by more than the per-step tolerance.
* Interval classification tolerates up to a few consecutive missed
  occurrences (a lapsed month, say) by allowing the gap to be a small
  integer multiple of the canonical interval, not just ~1x.

Both together are also what keeps genuinely irregular one-off purchases
at the same merchant OUT of the results: an irregular gap sequence fails
interval classification, and/or wildly varying amounts fail the
consistency check — a real recurring series has to pass both.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise

MIN_OCCURRENCES = 3
MAX_MISSED_MULTIPLE = 3          # tolerate a gap up to ~3x the nominal interval (2 missed occurrences)
AMOUNT_TOLERANCE_RATIO = 0.35    # 35% relative, compared to the immediately preceding occurrence — generous
                                  # enough to tolerate a real-world price increase (e.g. 9.99 -> 12.99) without
                                  # being so loose that genuinely unrelated amounts start passing (see
                                  # test_wild_amount_jump_not_detected_despite_regular_dates)
AMOUNT_TOLERANCE_MINOR_FLOOR = 100  # floor of 1.00 currency unit, so cheap subscriptions aren't overly strict

# (name, nominal_days, tolerance_days)
CANONICAL_INTERVALS: list[tuple[str, float, float]] = [
    ("weekly", 7, 2),
    ("monthly", 30.44, 5),
    ("quarterly", 91.31, 10),
    ("yearly", 365.25, 15),
]


@dataclass(frozen=True)
class RecurringCandidate:
    id: int
    key: str            # grouping identity — caller decides (e.g. merchant, lowercased/stripped)
    date: date
    amount_minor: int   # signed
    currency: str = "EUR"


@dataclass(frozen=True)
class RecurringSeries:
    key: str
    sign: int                              # +1 income, -1 expense
    interval: str                          # "weekly" | "monthly" | "quarterly" | "yearly"
    occurrences: tuple[RecurringCandidate, ...]   # chronological
    average_amount_minor: int
    last_amount_minor: int
    last_date: date
    currency: str = "EUR"


def _amounts_consistent(amounts: list[int]) -> bool:
    for prev, curr in pairwise(amounts):
        tolerance = max(AMOUNT_TOLERANCE_MINOR_FLOOR, round(abs(prev) * AMOUNT_TOLERANCE_RATIO))
        if abs(abs(curr) - abs(prev)) > tolerance:
            return False
    return True


def _fits(gaps: list[int], nominal: float, tolerance: float, max_multiple: int) -> bool:
    for gap in gaps:
        multiple = round(gap / nominal)
        if not (1 <= multiple <= max_multiple):
            return False
        if abs(gap - multiple * nominal) > tolerance:
            return False
    return True


def _classify_interval(gaps: list[int]) -> str | None:
    """Two passes, to resolve the inherent ambiguity between e.g. a
    ~91-day gap read as "quarterly, on time" vs. "monthly, missed two" —
    both fit the naive single-pass check. Pass 1 only accepts an interval
    if every gap fits with multiple==1 (no missed occurrences assumed at
    all); this always prefers the interval whose OWN cadence explains the
    data, rather than a shorter interval stretched by assumed misses.
    Only if no interval explains every gap with multiple==1 does pass 2
    fall back to allowing a few assumed missed occurrences."""
    for name, nominal, tolerance in CANONICAL_INTERVALS:
        if _fits(gaps, nominal, tolerance, max_multiple=1):
            return name
    for name, nominal, tolerance in CANONICAL_INTERVALS:
        if _fits(gaps, nominal, tolerance, max_multiple=MAX_MISSED_MULTIPLE):
            return name
    return None


def detect_recurring_series(candidates: list[RecurringCandidate]) -> list[RecurringSeries]:
    """Groups candidates by (key, sign) and returns the groups that pass
    both the interval-consistency and amount-consistency checks."""
    groups: dict[tuple[str, int, str], list[RecurringCandidate]] = defaultdict(list)
    for c in candidates:
        if c.amount_minor == 0:
            continue
        groups[(c.key, 1 if c.amount_minor > 0 else -1, c.currency)].append(c)

    results: list[RecurringSeries] = []
    for (key, sign, currency), group in groups.items():
        if len(group) < MIN_OCCURRENCES:
            continue

        ordered = tuple(sorted(group, key=lambda c: c.date))
        amounts = [c.amount_minor for c in ordered]
        if not _amounts_consistent(amounts):
            continue

        gaps = [(b.date - a.date).days for a, b in pairwise(ordered)]
        if any(g <= 0 for g in gaps):
            continue  # same-day or out-of-order entries — not a clean cadence

        interval = _classify_interval(gaps)
        if interval is None:
            continue

        results.append(RecurringSeries(
            key=key, sign=sign, interval=interval, occurrences=ordered,
            average_amount_minor=round(sum(amounts) / len(amounts)),
            last_amount_minor=ordered[-1].amount_minor, last_date=ordered[-1].date, currency=currency,
        ))

    return results


@dataclass(frozen=True)
class ForecastPoint:
    key: str
    date: date
    amount_minor: int  # projected using last_amount_minor — the most current price, not the historical average


# Calendar step per interval: weekly in days, everything else in whole
# months, so a monthly charge on the 1st stays on the 1st (a fixed
# 30-day step would produce both 1 Oct and 31 Oct, i.e. a doubled month).
_STEP_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}


def add_months(d: date, months: int) -> date:
    total = d.month - 1 + months
    year, month = d.year + total // 12, total % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def nth_occurrence_after(series: RecurringSeries, n: int) -> date:
    """Date of the n-th expected occurrence after the last real one. Always
    computed from the last real date (not by repeated stepping), so month
    ends don't drift (31 Jan -> 28 Feb -> 31 Mar, not -> 28 Mar)."""
    if series.interval == "weekly":
        return series.last_date + timedelta(days=7 * n)
    return add_months(series.last_date, _STEP_MONTHS[series.interval] * n)


def is_active(series: RecurringSeries, as_of: date) -> bool:
    """A series whose expected occurrences have stopped arriving (e.g. a
    cancelled subscription) must not be forecast forever. Active means
    at most one expected occurrence is missing so far."""
    tolerance = next(t for name, _nominal, t in CANONICAL_INTERVALS if name == series.interval)
    return as_of <= nth_occurrence_after(series, 2) + timedelta(days=tolerance)


def project_series_forward(series: RecurringSeries, horizon_end: date, start_after: date | None = None) -> list[ForecastPoint]:
    """Projects future occurrences of `series` up to and including
    `horizon_end`, stepping by the series' own calendar interval from its
    last real occurrence. Occurrences on or before `start_after` (e.g.
    today, for an occurrence that is expected but hasn't been imported
    yet) are skipped. The caller is responsible for choosing `horizon_end`
    to align with its monthly buckets (the last day of the last month)."""
    points: list[ForecastPoint] = []
    n = 1
    while (next_date := nth_occurrence_after(series, n)) <= horizon_end:
        if start_after is None or next_date > start_after:
            points.append(ForecastPoint(key=series.key, date=next_date, amount_minor=series.last_amount_minor))
        n += 1
    return points
