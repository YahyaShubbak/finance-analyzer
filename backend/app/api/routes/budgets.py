from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.db.session import get_session
from app.i18n import tr
from app.schemas.budget import BudgetRead, BudgetStatusItem, BudgetStatusResponse, BudgetUpsert
from app.services.budget_service import (
    BudgetServiceError,
    compute_budget_status,
    delete_budget,
    list_budgets,
    upsert_budget,
)

router = APIRouter(prefix="/api/budgets", tags=["budgets"])

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@router.get("", response_model=list[BudgetRead])
def list_budgets_route(session: Session = Depends(get_session)):
    return list_budgets(session)


# `:path` so categories containing "/" (e.g. "Haus/Garten") work.
@router.put("/{category:path}", response_model=BudgetRead)
def upsert_budget_route(category: str, payload: BudgetUpsert, session: Session = Depends(get_session)):
    try:
        return upsert_budget(session, category, payload.amount_minor, payload.currency)
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail=tr("A budget for category '{category}' already exists.", category=category)) from None


@router.delete("/{budget_id}", status_code=204)
def delete_budget_route(budget_id: int, session: Session = Depends(get_session)):
    if not delete_budget(session, budget_id):
        raise HTTPException(status_code=404, detail=tr("Budget not found"))


@router.get("/status", response_model=BudgetStatusResponse)
def budget_status_route(month: str, session: Session = Depends(get_session)):
    if not _MONTH_RE.match(month):
        raise HTTPException(status_code=422, detail=tr("Invalid 'month' — expected format YYYY-MM."))
    try:
        statuses = compute_budget_status(session, month)
    except BudgetServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return BudgetStatusResponse(
        month=month,
        items=[
            BudgetStatusItem(
                category=s.category, budget_minor=s.budget_minor, actual_minor=s.actual_minor,
                remaining_minor=s.remaining_minor, percent_used=s.percent_used,
                over_budget=s.over_budget, currency=s.currency,
            )
            for s in statuses
        ],
    )
