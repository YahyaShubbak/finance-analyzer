from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.models import Account, AccountType, CreditCardStatement
from app.db.session import get_session
from app.i18n import tr
from app.schemas.credit_card import CreditCardSummary, StatementSummary
from app.services.credit_card_service import build_statement_summary, list_credit_card_summaries

router = APIRouter(prefix="/api/credit-cards", tags=["credit-cards"])


@router.get("", response_model=list[CreditCardSummary])
def list_credit_cards(session: Session = Depends(get_session)):
    return list_credit_card_summaries(session)


@router.get("/{account_id}/statements", response_model=list[StatementSummary])
def list_statements(account_id: int, session: Session = Depends(get_session)):
    account = session.get(Account, account_id)
    if account is None or account.account_type != AccountType.CREDIT_CARD:
        raise HTTPException(status_code=404, detail=tr("Credit-card account not found"))

    statements = session.exec(
        select(CreditCardStatement)
        .where(CreditCardStatement.account_id == account_id)
        .order_by(CreditCardStatement.statement_period_end.desc())
    ).all()
    return [build_statement_summary(session, s) for s in statements]
