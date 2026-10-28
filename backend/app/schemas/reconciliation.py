from __future__ import annotations

from pydantic import BaseModel


class TransactionBrief(BaseModel):
    id: int
    transaction_date: str
    merchant: str | None
    normalized_description: str
    category: str | None
    amount_minor: int
    currency: str
    transaction_type: str
    account_id: int
    account_name: str
    is_duplicate: bool
    is_transfer: bool
    source_filename: str | None


class BankPaymentInfo(BaseModel):
    status: str  # "matched" | "suggested" | "not_found"
    transaction: TransactionBrief | None = None
    candidates: list[TransactionBrief] = []  # populated only when status == "suggested"
    # An exact, unambiguous match the user can confirm with one click.
    recommended_transaction_id: int | None = None


class ReconciliationDetail(BaseModel):
    reconciliation_id: int | None  # None until the first explicit action persists one
    statement_id: int
    account_id: int
    account_name: str
    statement_period_start: str | None
    statement_period_end: str | None
    currency: str

    transactions: list[TransactionBrief]
    transaction_total_minor: int

    statement_total_minor: int | None
    other_totals: dict[str, int]

    bank_payment: BankPaymentInfo

    diff_transactions_vs_statement_minor: int | None
    diff_statement_vs_bank_minor: int | None

    status: str
    explanation_tags: list[str]
    user_resolution_tags: list[str]

    resolved_by_user: bool
    resolution_notes: str | None

    source_import_filename: str | None


class ResolveReconciliationRequest(BaseModel):
    notes: str | None = None
    tags: list[str] | None = None


class SelectBankPaymentRequest(BaseModel):
    transaction_id: int
