"""Information about this installation, shown in Settings so the user
always knows where their data lives — and starting over (reset)."""
from __future__ import annotations

import os
import signal
import threading
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.config import APP_VERSION, settings
from app.db.session import get_session, maintenance_lock
from app.i18n import tr
from app.services.reset_service import reset_everything

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


def _end_as_ctrl_c() -> None:
    signal.raise_signal(signal.SIGINT)


class StopRequest(BaseModel):
    pid: int  # the process that is meant: another copy of the app on this port must not end


@router.post("/stop", status_code=202)
def stop(payload: StopRequest):
    """Ends the app the way Ctrl+C in its window does: requests under way
    are finished and the database is closed. For `python -m app --stop` on
    Windows, where ending a process from outside cuts it off at once."""
    if payload.pid != os.getpid():
        raise HTTPException(status_code=409, detail=tr("This is not the app that was asked to stop."))
    threading.Timer(0.2, _end_as_ctrl_c).start()  # (after this answer is on its way)
    return {"stopping": True}


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
    with maintenance_lock:  # not while an import, removal or restore is writing
        result = reset_everything(session, delete_backups=payload.delete_backups)
    return ResetResponse(rows_deleted=result.rows_deleted, files_deleted=result.files_deleted)
