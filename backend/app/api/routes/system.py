"""Information about this installation, shown in Settings so the user
always knows where their data lives — and starting over (reset)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.config import APP_VERSION, settings
from app.db.session import get_session

router = APIRouter(prefix="/api/system", tags=["system"])

_APP_DIR = Path(__file__).resolve().parents[2]  # backend/app


def _code_stamp() -> float:
    """Newest modification time of the backend's code. Python reads it once,
    at start: after an update (git pull, new version) the running process
    still serves the old code until it is restarted."""
    return max((p.stat().st_mtime for p in _APP_DIR.rglob("*.py") if "__pycache__" not in p.parts), default=0.0)


_STARTED_WITH = _code_stamp()


class SystemInfo(BaseModel):
    version: str
    data_dir: str
    database_path: str
    imports_dir: str
    backups_dir: str
    using_legacy_layout: bool
    restart_needed: bool  # the code on disk is newer than the running process


@router.get("/info", response_model=SystemInfo)
def system_info():
    return SystemInfo(
        version=APP_VERSION,
        data_dir=str(settings.data_dir),
        database_path=str(settings.database_path),
        imports_dir=str(settings.imports_dir),
        backups_dir=str(settings.backups_dir),
        using_legacy_layout=settings.using_legacy_layout,
        restart_needed=_code_stamp() > _STARTED_WITH,
    )


class ResetRequest(BaseModel):
    confirm: Literal["RESET"]  # typed on purpose: this deletes everything
    delete_backups: bool = False


class ResetResponse(BaseModel):
    rows_deleted: int
    files_deleted: int


@router.post("/reset", response_model=ResetResponse)
def reset(payload: ResetRequest, session: Session = Depends(get_session)):
    """Delete all data: bookings, imports with their originals, accounts,
    own categories and rules, budgets, points, exports — and the backups
    only when asked."""
    from app.db.session import maintenance_lock
    from app.services.reset_service import reset_everything

    with maintenance_lock:  # not while an import, removal or restore is writing
        result = reset_everything(session, delete_backups=payload.delete_backups)
    return ResetResponse(rows_deleted=result.rows_deleted, files_deleted=result.files_deleted)
