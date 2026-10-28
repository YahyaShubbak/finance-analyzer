"""Bonus points from card statements (app/services/points_service.py)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db.models import PointsProgram
from app.db.session import get_session
from app.i18n import tr
from app.schemas.points import PointsProgramSummary, PointsProgramUpdate
from app.services.points_service import points_overview

router = APIRouter(prefix="/api/points", tags=["points"])


@router.get("", response_model=list[PointsProgramSummary])
def list_points(session: Session = Depends(get_session)):
    return points_overview(session)


@router.patch("/programs/{program_id}", response_model=PointsProgramSummary)
def update_program(program_id: int, payload: PointsProgramUpdate, session: Session = Depends(get_session)):
    program = session.get(PointsProgram, program_id)
    if program is None:
        raise HTTPException(status_code=404, detail=tr("This bonus program doesn't exist."))
    if payload.name is not None:
        program.name = payload.name
    if payload.value_per_100 is not None:
        program.value_per_100 = payload.value_per_100
        program.value_set_by_user = True
    session.add(program)
    session.commit()
    return next(p for p in points_overview(session) if p["id"] == program_id)
