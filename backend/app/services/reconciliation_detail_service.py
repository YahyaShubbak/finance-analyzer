"""Builds the full reconciliation detail payload for the frontend: the
three-level relationship (individual transactions -> statement -> bank
payment), both independent differences, evidence-based explanations, and
the audit trail back to source documents. All computation happens here —
the frontend only renders what this returns.
"""
from __future__ import annotations

import json

from sqlmodel import Session, select

from app.db.chunks import chunked
from app.db.models import Account, CreditCardStatement, ImportRecord, Reconciliation, Transaction
from app.i18n import tr
from app.reconciliation.engine import (
    ReconciliationError,
    compute_reconciliation,
    current_bank_payment,
    find_automatic_match,
    get_suggested_payments,
    statement_transaction_ids,
)
from app.schemas.reconciliation import BankPaymentInfo, ReconciliationDetail, TransactionBrief


def _to_brief(session: Session, tx: Transaction, accounts_by_id: dict[int, Account]) -> TransactionBrief:
    source_filename = None
    if tx.raw_transaction and tx.raw_transaction.import_record:
        source_filename = tx.raw_transaction.import_record.filename
    account = accounts_by_id.get(tx.account_id)
    return TransactionBrief(
        id=tx.id,
        transaction_date=tx.transaction_date.isoformat(),
        merchant=tx.merchant,
        normalized_description=tx.normalized_description,
        category=tx.category,
        amount_minor=tx.amount_minor,
        currency=tx.currency,
        transaction_type=tx.transaction_type.value,
        account_id=tx.account_id,
        account_name=account.name if account else "Unknown",
        is_duplicate=tx.is_duplicate,
        is_transfer=tx.is_transfer,
        source_filename=source_filename,
    )


def build_reconciliation_detail(session: Session, statement_id: int) -> ReconciliationDetail:
    """Read-only: computes everything fresh from the current data and
    never links or unlinks a payment (see app.reconciliation.engine)."""
    statement = session.get(CreditCardStatement, statement_id)
    if statement is None:
        raise ReconciliationError(tr("Unknown statement_id={statement_id}", statement_id=statement_id))

    bank_tx = current_bank_payment(session, statement)
    figures = compute_reconciliation(session, statement, bank_tx)
    stored = session.exec(select(Reconciliation).where(Reconciliation.statement_id == statement_id)).first()

    accounts_by_id = {a.id: a for a in session.exec(select(Account)).all()}
    account = accounts_by_id.get(statement.account_id)

    # Individual credit-card transactions belonging to this statement.
    statement_tx = sorted(
        (t for chunk in chunked(statement_transaction_ids(session, statement)) for t in session.exec(
            select(Transaction).where(Transaction.id.in_(chunk), Transaction.account_id == statement.account_id)
        ).all()),
        key=lambda t: (t.transaction_date, t.id),
    )

    # Bank payment: linked / suggestions for the user to confirm / nothing found.
    bank_payment: BankPaymentInfo
    if bank_tx is not None:
        bank_payment = BankPaymentInfo(status="matched", transaction=_to_brief(session, bank_tx, accounts_by_id))
    else:
        candidates = get_suggested_payments(session, statement)
        automatic = find_automatic_match(session, statement)
        if candidates:
            bank_payment = BankPaymentInfo(
                status="suggested",
                candidates=[_to_brief(session, c, accounts_by_id) for c in candidates],
                recommended_transaction_id=automatic.id if automatic else None,
            )
        else:
            bank_payment = BankPaymentInfo(status="not_found")

    source_import = session.get(ImportRecord, statement.import_id)

    other_totals = json.loads(statement.other_totals_json) if statement.other_totals_json else {}
    user_resolution_tags = (
        json.loads(stored.user_resolution_tags_json) if stored and stored.user_resolution_tags_json else []
    )

    return ReconciliationDetail(
        reconciliation_id=stored.id if stored else None,
        statement_id=statement.id,
        account_id=statement.account_id,
        account_name=account.name if account else "Unknown",
        statement_period_start=statement.statement_period_start.isoformat() if statement.statement_period_start else None,
        statement_period_end=statement.statement_period_end.isoformat() if statement.statement_period_end else None,
        currency=statement.currency,
        transactions=[_to_brief(session, t, accounts_by_id) for t in statement_tx],
        transaction_total_minor=figures.transaction_total_minor,
        statement_total_minor=statement.statement_total_minor,
        other_totals=other_totals,
        bank_payment=bank_payment,
        diff_transactions_vs_statement_minor=figures.diff_transactions_vs_statement_minor,
        diff_statement_vs_bank_minor=figures.diff_statement_vs_bank_minor,
        status=figures.status.value,
        explanation_tags=figures.explanation_tags,
        user_resolution_tags=user_resolution_tags,
        resolved_by_user=bool(stored and stored.resolved_by_user),
        resolution_notes=stored.resolution_notes if stored else None,
        source_import_filename=source_import.filename if source_import else None,
    )
