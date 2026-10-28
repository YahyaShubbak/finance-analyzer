from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db.models import CreditCardStatement, Transaction
from app.db.session import get_session
from app.i18n import tr
from app.reconciliation.engine import ReconciliationError, reconcile_statement, resolve_reconciliation
from app.schemas.reconciliation import (
    ReconciliationDetail,
    ResolveReconciliationRequest,
    SelectBankPaymentRequest,
)
from app.services.reconciliation_detail_service import build_reconciliation_detail

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])


@router.get("/statements/{statement_id}", response_model=ReconciliationDetail)
def get_reconciliation_detail(statement_id: int, session: Session = Depends(get_session)):
    try:
        return build_reconciliation_detail(session, statement_id)
    except ReconciliationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _statement_or_404(session: Session, statement_id: int) -> CreditCardStatement:
    statement = session.get(CreditCardStatement, statement_id)
    if statement is None:
        raise HTTPException(status_code=404, detail=tr("Statement not found"))
    return statement


@router.post("/statements/{statement_id}/select-bank-payment", response_model=ReconciliationDetail)
def select_bank_payment(statement_id: int, payload: SelectBankPaymentRequest, session: Session = Depends(get_session)):
    _statement_or_404(session, statement_id)
    tx = session.get(Transaction, payload.transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail=tr("Transaction not found"))
    try:
        reconcile_statement(session, statement_id, bank_debit_transaction_id=payload.transaction_id)
    except ReconciliationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return build_reconciliation_detail(session, statement_id)


@router.post("/statements/{statement_id}/clear-bank-payment", response_model=ReconciliationDetail)
def clear_bank_payment(statement_id: int, session: Session = Depends(get_session)):
    """The linked payment is wrong: unlink it (it becomes an ordinary
    expense again) and leave the statement pending."""
    _statement_or_404(session, statement_id)
    reconcile_statement(session, statement_id, clear_bank_payment=True)
    return build_reconciliation_detail(session, statement_id)


@router.post("/statements/{statement_id}/find-payment", response_model=ReconciliationDetail)
def find_payment(statement_id: int, session: Session = Depends(get_session)):
    """Explicitly re-run automatic matching (exact, unambiguous only)."""
    _statement_or_404(session, statement_id)
    reconcile_statement(session, statement_id, auto_match=True)
    return build_reconciliation_detail(session, statement_id)


@router.post("/statements/{statement_id}/resolve", response_model=ReconciliationDetail)
def resolve(statement_id: int, payload: ResolveReconciliationRequest, session: Session = Depends(get_session)):
    _statement_or_404(session, statement_id)
    reconciliation = reconcile_statement(session, statement_id)  # persists the row if it doesn't exist yet
    try:
        resolve_reconciliation(session, reconciliation.id, notes=payload.notes, tags=payload.tags)
    except ReconciliationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return build_reconciliation_detail(session, statement_id)
