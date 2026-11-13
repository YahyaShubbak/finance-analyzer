from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.i18n import tr


class PointsMonth(BaseModel):
    month: str  # "YYYY-MM"
    earned: int
    redeemed: int  # negative
    balance: int   # at the month's end


class PointsMerchant(BaseModel):
    merchant: str
    points: int
    bookings: int
    spent_minor: int


class PointsRedemption(BaseModel):
    date: str
    points: int
    value_minor: int | None = None


class PointsBooking(BaseModel):
    transaction_id: int
    date: str
    merchant: str
    amount_minor: int
    currency: str
    points: int


class PointsProgramSummary(BaseModel):
    id: int
    name: str
    unit: str
    value_per_100: int  # cents that 100 points are worth
    value_set_by_user: bool
    currency: str = "EUR"  # ... of the card the program's statements belong to
    balance: int
    balance_value_minor: int
    balance_stated: bool  # from a statement's stated balance (else: the sum of what was read)
    balance_as_of: str
    earned: int
    redeemed: int
    earned_this_year: int
    redeemed_this_year: int
    cashback_percent: float | None  # value of the points earned / card spending of those statements
    months: list[PointsMonth]
    merchants: list[PointsMerchant]
    redemptions: list[PointsRedemption]
    bookings: list[PointsBooking]


class PointsProgramUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    value_per_100: int | None = Field(default=None, ge=0, le=100_000)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError(tr("must not be empty"))
        return value.strip() if value is not None else None
