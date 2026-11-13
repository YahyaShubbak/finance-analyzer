"""Backup/restore endpoints. Read-only listing and creation are always
safe; restore requires explicit confirmation and is validated before
anything is touched — see app.services.backup_service for the full
safety design.

Endpoints are plain `def` (not `async def`): backup work is blocking file
I/O and must run in the thread pool rather than stall the event loop.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.uploads import reject_oversized_request, save_upload
from app.config import settings
from app.i18n import tr
from app.schemas.backup import BackupInfoRead, RestoreResultRead
from app.services.backup_service import (
    BackupError,
    create_backup_zip,
    delete_backup,
    is_backup_zip,
    list_backups,
    restore_from_backup,
)

router = APIRouter(prefix="/api/backup", tags=["backup"])


@router.get("", response_model=list[BackupInfoRead])
def list_backups_route():
    return [
        BackupInfoRead(filename=b.filename, created_at=b.created_at, size_bytes=b.size_bytes, counts=b.counts)
        for b in list_backups()
    ]


@router.post("/create", response_model=BackupInfoRead)
def create_backup_route():
    try:
        zip_path = create_backup_zip()
    except BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    for b in list_backups():
        if b.filename == zip_path.name:
            return BackupInfoRead(filename=b.filename, created_at=b.created_at, size_bytes=b.size_bytes, counts=b.counts)
    raise HTTPException(status_code=500, detail=tr("Backup was created but could not be read back."))


def _safe_backup_path(filename: str) -> Path:
    # Reject any path traversal — filename must resolve to a plain file
    # directly inside backups_dir.
    backups_dir = settings.backups_dir.resolve()
    if "\x00" in filename or len(filename) > 255:
        raise HTTPException(status_code=404, detail=tr("Backup not found."))
    candidate = (backups_dir / filename).resolve()
    if candidate.parent != backups_dir or candidate.suffix != ".zip" or not candidate.is_file():
        raise HTTPException(status_code=404, detail=tr("Backup not found."))
    return candidate


@router.get("/{filename}/download")
def download_backup_route(filename: str):
    path = _safe_backup_path(filename)
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.delete("/{filename}", status_code=204)
def delete_backup_route(filename: str):
    """Removes a backup from this machine (they hold every original
    document and are never removed by themselves, except the oldest safety
    copies made before a restore)."""
    path = _safe_backup_path(filename)
    if not is_backup_zip(path):  # some other ZIP in that folder: not the app's
        raise HTTPException(status_code=404, detail=tr("Backup not found."))
    try:
        delete_backup(path)
    except BackupError as exc:  # e.g. open in another program
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/restore", response_model=RestoreResultRead)
def restore_backup_route(request: Request, file: UploadFile, confirm: bool = Form(...)):
    if not confirm:
        raise HTTPException(status_code=400, detail=tr("Restore requires explicit confirmation."))
    reject_oversized_request(request, settings.max_backup_upload_bytes)

    settings.ensure_directories()
    upload_path = settings.staging_dir / f"restore-upload-{uuid.uuid4().hex}.zip"
    try:
        save_upload(file, upload_path, settings.max_backup_upload_bytes)
        result = _restore(upload_path)
    finally:
        upload_path.unlink(missing_ok=True)
    # The temporary upload name means nothing to the user.
    result.restored_from = file.filename or "uploaded backup"
    return result


@router.post("/{filename}/restore", response_model=RestoreResultRead)
def restore_existing_backup_route(filename: str, confirm: bool = Form(...)):
    """Restore from a backup already listed on this machine (usable
    without needing to locate/re-upload the file)."""
    if not confirm:
        raise HTTPException(status_code=400, detail=tr("Restore requires explicit confirmation."))
    return _restore(_safe_backup_path(filename))


def _restore(path: Path) -> RestoreResultRead:
    try:
        result = restore_from_backup(path, confirm=True)
    except BackupError as exc:  # includes BackupValidationError
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RestoreResultRead(
        restored_from=result.restored_from, safety_backup=result.safety_backup, counts=result.counts
    )
