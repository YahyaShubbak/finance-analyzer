from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.api.params import parse_account_ids
from app.db.session import get_session
from app.normalization.recurring import is_active
from app.schemas.recurring import ForecastResponse, MonthlyForecastPoint, RecurringSeriesItem, RecurringSeriesResponse
from app.services.recurring_service import (
    get_forecast,
    get_recurring_series,
    next_expected_date,
    series_currency,
    series_label,
)

router = APIRouter(prefix="/api/recurring", tags=["recurring"])


@router.get("/series", response_model=RecurringSeriesResponse)
def list_recurring_series(account_id: str | None = None, session: Session = Depends(get_session)):
    series_list = get_recurring_series(session, parse_account_ids(account_id))
    items = [
        RecurringSeriesItem(
            key=s.key,
            label=series_label(session, s),
            sign="income" if s.sign > 0 else "expense",
            interval=s.interval,
            occurrence_count=len(s.occurrences),
            average_amount_minor=s.average_amount_minor,
            last_amount_minor=s.last_amount_minor,
            last_date=s.last_date,
            next_expected_date=next_expected_date(s),
            currency=series_currency(session, s),
            is_active=is_active(s, date.today()),
        )
        for s in series_list
    ]
    items.sort(key=lambda i: (not i.is_active, i.next_expected_date))
    return RecurringSeriesResponse(series=items)


@router.get("/forecast", response_model=ForecastResponse)
def forecast(
    months: int = Query(3, ge=1, le=24),
    account_id: str | None = None,
    session: Session = Depends(get_session),
):
    result = get_forecast(session, months=months, account_ids=parse_account_ids(account_id))
    return ForecastResponse(
        as_of=result.as_of,
        months=months,
        series_count=result.series_count,
        points=[
            MonthlyForecastPoint(
                month=p.month, currency=p.currency, recurring_net_minor=p.recurring_net_minor,
                baseline_net_minor=p.baseline_net_minor, projected_net_minor=p.projected_net_minor,
            )
            for p in result.points
        ],
    )
