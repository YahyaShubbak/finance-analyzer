"""Wires app.normalization.recurring's pure detection/projection logic
into the actual data pipeline. Computed on demand — no persisted
RecurringSeries table and no sync-on-edit logic. Personal-finance
transaction volumes (thousands, not millions) make live computation fast
enough that this simplicity is worth it.

Eligible transactions are loaded via analytics_service._base_query — the
exact same is_duplicate/is_transfer/archived-account exclusion used by
every other aggregate in the app, so e.g. a monthly credit-card bill
payment that is already excluded as a transfer never shows up here as a
"recurring payment".

Series and forecasts are kept per currency — amounts in different
currencies are never added together.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, select

from app.db.models import Account, Transaction
from app.normalization.recurring import (
    RecurringCandidate,
    RecurringSeries,
    add_months,
    detect_recurring_series,
    is_active,
    nth_occurrence_after,
    project_series_forward,
)
from app.services import analytics_service

DEFAULT_FORECAST_MONTHS = 3
NON_RECURRING_BASELINE_MONTHS = 3


def _eligible_transactions(session: Session, account_ids: list[int] | None = None) -> list[Transaction]:
    return list(session.exec(analytics_service._base_query(session, account_ids, None, None)).all())


def _group_key(t: Transaction) -> str:
    return (t.merchant or t.normalized_description).strip().lower()


def series_label(session: Session, series: RecurringSeries) -> str:
    """The merchant as written on the series' latest transaction."""
    latest = session.get(Transaction, series.occurrences[-1].id) if series.occurrences else None
    return (latest.merchant or latest.normalized_description).strip() if latest else series.key


def get_recurring_series(session: Session, account_ids: list[int] | None = None) -> list[RecurringSeries]:
    transactions = _eligible_transactions(session, account_ids)
    candidates = [
        RecurringCandidate(
            id=t.id, key=_group_key(t), date=t.transaction_date, amount_minor=t.amount_minor, currency=t.currency
        )
        for t in transactions
    ]
    return detect_recurring_series(candidates)


@dataclass
class MonthlyForecast:
    month: str  # "YYYY-MM"
    currency: str
    recurring_net_minor: int
    baseline_net_minor: int
    projected_net_minor: int


@dataclass
class ForecastResult:
    as_of: date
    series_count: int
    points: list[MonthlyForecast]


def get_forecast(
    session: Session,
    months: int = DEFAULT_FORECAST_MONTHS,
    as_of: date | None = None,
    account_ids: list[int] | None = None,
) -> ForecastResult:
    as_of = as_of or date.today()
    all_series = get_recurring_series(session, account_ids)
    # Every series' transactions are excluded from the baseline, but only
    # still-active series are projected forward.
    recurring_tx_ids = {c.id for s in all_series for c in s.occurrences}
    series_list = [s for s in all_series if is_active(s, as_of)]

    all_tx = _eligible_transactions(session, account_ids)
    month_start = as_of.replace(day=1)
    baseline_start = add_months(month_start, -NON_RECURRING_BASELINE_MONTHS)
    baseline_by_currency: dict[str, int] = defaultdict(int)
    for t in all_tx:
        if t.id not in recurring_tx_ids and baseline_start <= t.transaction_date < month_start:
            baseline_by_currency[t.currency] += t.amount_minor

    month_labels = []
    cursor = add_months(month_start, 1)
    for _ in range(months):
        month_labels.append(cursor.strftime("%Y-%m"))
        cursor = add_months(cursor, 1)

    # horizon_end must be the LAST day of the last forecasted month.
    last_year, last_month = (int(x) for x in month_labels[-1].split("-"))
    horizon_end = date(last_year, last_month, calendar.monthrange(last_year, last_month)[1])

    recurring_by_key: dict[tuple[str, str], int] = defaultdict(int)
    for s in series_list:
        for p in project_series_forward(s, horizon_end):
            recurring_by_key[(p.date.strftime("%Y-%m"), s.currency)] += p.amount_minor

    currencies = sorted(set(baseline_by_currency) | {s.currency for s in series_list}) or [_default_currency(session)]
    points = []
    for currency in currencies:
        # Fixed divisor (not "number of months with any activity") so a
        # quiet month still pulls the average down.
        baseline = round(baseline_by_currency.get(currency, 0) / NON_RECURRING_BASELINE_MONTHS)
        for m in month_labels:
            recurring = recurring_by_key.get((m, currency), 0)
            points.append(MonthlyForecast(
                month=m, currency=currency, recurring_net_minor=recurring,
                baseline_net_minor=baseline, projected_net_minor=recurring + baseline,
            ))
    return ForecastResult(as_of=as_of, series_count=len(series_list), points=points)


def _default_currency(session: Session) -> str:
    account = session.exec(select(Account).where(Account.is_archived == False)).first()  # noqa: E712
    return account.currency if account else "EUR"


def next_expected_date(series: RecurringSeries, as_of: date | None = None) -> date:
    """The next occurrence on or after `as_of` (today); for an inactive
    series simply the first one that didn't arrive."""
    as_of = as_of or date.today()
    if not is_active(series, as_of):
        return nth_occurrence_after(series, 1)
    n = 1
    while (candidate := nth_occurrence_after(series, n)) < as_of:
        n += 1
    return candidate


def series_currency(_session: Session, series: RecurringSeries) -> str:
    return series.currency
