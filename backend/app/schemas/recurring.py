from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class RecurringSeriesItem(BaseModel):
    key: str
    label: str = ""      # the merchant as written on its latest transaction ("Beispiel GmbH")
    sign: str            # "income" | "expense"
    interval: str         # "weekly" | "monthly" | "quarterly" | "yearly"
    occurrence_count: int
    average_amount_minor: int
    last_amount_minor: int
    last_date: date
    next_expected_date: date
    currency: str
    is_active: bool = True  # False once expected occurrences stopped arriving (e.g. cancelled)


class RecurringSeriesResponse(BaseModel):
    series: list[RecurringSeriesItem]


class MonthlyForecastPoint(BaseModel):
    month: str  # "2026-06"
    currency: str
    recurring_net_minor: int
    baseline_net_minor: int
    projected_net_minor: int


class ForecastResponse(BaseModel):
    as_of: date
    months: int
    series_count: int
    points: list[MonthlyForecastPoint]
