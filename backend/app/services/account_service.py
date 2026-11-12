"""Account-level aggregates: transaction counts and the three distinct
balance figures shown to the user (spec Milestone 4, Feature 4):

* transactions_balance_minor — net of ALL imported, non-duplicate
  transactions for the account. Purely derived from imported data; never
  affected by an opening balance. Only as accurate as the imported
  history is complete.
* opening_balance_minor / opening_balance_date — optional, user-entered,
  never derived from transactions. Kept completely separate so it's
  always clear which number came from where.
* current_balance_minor — the headline balance: opening_balance_minor
  (or 0, if not set) plus the sum of non-duplicate transactions dated on
  or after opening_balance_date (or ALL transactions, if no opening date
  is set — which makes this identical to transactions_balance_minor by
  default, preserving existing behavior for accounts with no opening
  balance configured).

This never changes income/expense totals, reports, or reconciliation —
those all continue to operate over the full transaction history exactly
as before; this module only affects how account BALANCE is displayed.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import case
from sqlmodel import Session, func, select

from app.db.models import Account, Transaction
from app.schemas.account import AccountRead


@dataclass
class AccountSummary:
    transaction_count: int
    transactions_balance_minor: int
    current_balance_minor: int


def compute_account_summaries(session: Session) -> dict[int, AccountSummary]:
    """One aggregate query for all accounts. The opening balance is the
    balance at the START of opening_balance_date, so transactions on that
    date are added to it."""
    counted_since_opening = case(
        ((Account.opening_balance_date == None) | (Transaction.transaction_date >= Account.opening_balance_date),  # noqa: E711
         Transaction.amount_minor),
        else_=0,
    )
    rows = session.exec(
        select(
            Account.id,
            Account.opening_balance_minor,
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.amount_minor), 0),
            func.coalesce(func.sum(counted_since_opening), 0),
        )
        .join(Transaction, Transaction.account_id == Account.id)
        .where(Transaction.is_duplicate == False)  # noqa: E712
        .group_by(Account.id)
    ).all()

    return {
        account_id: AccountSummary(
            transaction_count=count,
            transactions_balance_minor=int(total),
            current_balance_minor=(opening or 0) + int(since_opening),
        )
        for account_id, opening, count, total, since_opening in rows
    }


def account_read(account: Account, summaries: dict[int, AccountSummary]) -> AccountRead:
    """The account as the API shows it (the one place that builds it)."""
    summary = summaries.get(account.id, AccountSummary(0, 0, account.opening_balance_minor or 0))
    return AccountRead(
        id=account.id,
        name=account.name,
        account_type=account.account_type,
        currency=account.currency,
        iban=account.iban,
        created_at=account.created_at,
        is_archived=account.is_archived,
        transaction_count=summary.transaction_count,
        transactions_balance_minor=summary.transactions_balance_minor,
        opening_balance_minor=account.opening_balance_minor,
        opening_balance_date=account.opening_balance_date,
        current_balance_minor=summary.current_balance_minor,
    )
