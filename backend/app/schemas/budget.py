from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.importers.parsing_utils import MAX_AMOUNT_MINOR
from app.schemas.account import validate_currency


class BudgetUpsert(BaseModel):
    amount_minor: int = Field(gt=0, le=MAX_AMOUNT_MINOR)
    currency: str = "EUR"

    @field_validator("currency")
    @classmethod
    def _currency(cls, v: str) -> str:
        return validate_currency(v)


class BudgetRead(BaseModel):
    id: int
    category: str
    amount_minor: int
    currency: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BudgetStatusItem(BaseModel):
    category: str
    budget_minor: int
    actual_minor: int
    remaining_minor: int
    percent_used: float
    over_budget: bool
    currency: str


class BudgetStatusResponse(BaseModel):
    month: str
    items: list[BudgetStatusItem]
