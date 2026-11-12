"""Aggregates for the Credit Cards page. Reconciliation status shown here
is always freshly computed from the current data, read-only — viewing
this page never links payments or changes any totals.
"""
from __future__ import annotations

from sqlmodel import Session, select

from app.db.models import Account, AccountType, CreditCardStatement, RawTransaction, Transaction, TransactionType
from app.reconciliation.engine import compute_reconciliation, current_bank_payment, statement_transaction_ids
from app.schemas.credit_card import CreditCardSummary, StatementSummary
from app.services.account_service import account_read, compute_account_summaries


def _count_statement_transactions(session: Session, statement: CreditCardStatement) -> int:
    """The bookings the statement lists — also those another file (e.g. the
    card's export) brought first, which its rows were skipped as duplicates of."""
    return len(statement_transaction_ids(session, statement))


def build_statement_summary(session: Session, statement: CreditCardStatement) -> StatementSummary:
    reconciliation = compute_reconciliation(session, statement, current_bank_payment(session, statement))
    return StatementSummary(
        id=statement.id,
        account_id=statement.account_id,
        statement_period_start=statement.statement_period_start.isoformat() if statement.statement_period_start else None,
        statement_period_end=statement.statement_period_end.isoformat() if statement.statement_period_end else None,
        statement_total_minor=statement.statement_total_minor,
        currency=statement.currency,
        transaction_count=_count_statement_transactions(session, statement),
        reconciliation_status=reconciliation.status.value,
        difference_minor=reconciliation.difference_minor,
    )


def _payment_links(session: Session, account_id: int) -> tuple[int, int]:
    """(paired, unpaired) payments onto the card outside its statements."""
    statement_imports = select(CreditCardStatement.import_id)
    rows = session.exec(
        select(Transaction.transfer_pair_id)
        .join(RawTransaction, RawTransaction.id == Transaction.raw_transaction_id)
        .where(
            RawTransaction.import_id.not_in(statement_imports),  # a statement's payment is settled by reconciliation
            Transaction.account_id == account_id,
            Transaction.amount_minor > 0,
            Transaction.transaction_type == TransactionType.TRANSFER,
            Transaction.is_duplicate == False,  # noqa: E712
            Transaction.settles_statement_id == None,  # noqa: E711
        )
    ).all()
    linked = sum(1 for pair in rows if pair is not None)
    return linked, len(rows) - linked


def list_credit_card_summaries(session: Session) -> list[CreditCardSummary]:
    accounts = session.exec(select(Account).where(Account.account_type == AccountType.CREDIT_CARD)).all()
    account_summaries = compute_account_summaries(session)

    results = []
    for account in accounts:
        statements = session.exec(
            select(CreditCardStatement)
            .where(CreditCardStatement.account_id == account.id)
            .order_by(CreditCardStatement.statement_period_end.desc())
        ).all()

        shown = account_read(account, account_summaries)
        latest = build_statement_summary(session, statements[0]) if statements else None

        linked, unlinked = _payment_links(session, account.id)
        results.append(CreditCardSummary(
            account=shown, statement_count=len(statements), latest_statement=latest,
            payments_linked=linked, payments_unlinked=unlinked,
        ))

    return results
