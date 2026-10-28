from __future__ import annotations

from pydantic import BaseModel

from app.schemas.transaction import TransactionRead


class CurrencyTotals(BaseModel):
    currency: str
    income_minor: int
    expenses_minor: int
    net_minor: int
    transaction_count: int


class TotalsResponse(BaseModel):
    income_minor: int | None      # None when is_mixed_currency — see by_currency instead
    expenses_minor: int | None
    net_minor: int | None
    transaction_count: int
    currency: str | None           # the single common currency, or None when mixed/empty
    is_mixed_currency: bool
    by_currency: list[CurrencyTotals] | None = None


class CategoryBreakdownItem(BaseModel):
    category: str
    currency: str
    amount_minor: int  # positive magnitude spent in this category (in this currency)


class LocationBreakdownItem(BaseModel):
    country: str | None  # ISO 3166-1 alpha-2; None (and online false): no known place
    city: str | None
    online: bool
    currency: str
    amount_minor: int
    transaction_count: int


class CategoryTransactionsResponse(BaseModel):
    items: list[TransactionRead]
    total: int
    page: int
    page_size: int
    amount_minor: int  # net spending of ALL matching transactions (not just this page) — the bar's amount


# The transactions behind one row of /by-location: same shape.
LocationTransactionsResponse = CategoryTransactionsResponse


class MonthlyPoint(BaseModel):
    month: str  # "2026-03"
    currency: str
    income_minor: int
    expenses_minor: int


class AccountBreakdownItem(BaseModel):
    account_id: int
    account_name: str
    account_type: str
    currency: str  # the account's nominal currency — see AccountBreakdown docstring for limitations
    income_minor: int
    expenses_minor: int
    net_minor: int
    transaction_count: int


class CurrencyTransfersSummary(BaseModel):
    currency: str
    total_transferred_minor: int
    transfer_count: int


class TransfersSummaryResponse(BaseModel):
    total_transferred_minor: int | None   # None when is_mixed_currency
    transfer_count: int
    currency: str | None
    is_mixed_currency: bool
    by_currency: list[CurrencyTransfersSummary] | None = None
