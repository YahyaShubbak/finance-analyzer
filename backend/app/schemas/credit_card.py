from __future__ import annotations

from pydantic import BaseModel

from app.schemas.account import AccountRead


class StatementSummary(BaseModel):
    id: int
    account_id: int
    statement_period_start: str | None
    statement_period_end: str | None
    statement_total_minor: int | None
    currency: str
    transaction_count: int
    reconciliation_status: str  # "reconciled" | "mismatch" | "pending"
    difference_minor: int | None


class CreditCardSummary(BaseModel):
    account: AccountRead
    statement_count: int
    latest_statement: StatementSummary | None
    # Payments onto the card that no statement accounts for (cards whose
    # exports list bookings, not statements): paired with the bank debit
    # they came from, or not (e.g. no bank statements for that time).
    payments_linked: int = 0
    payments_unlinked: int = 0
