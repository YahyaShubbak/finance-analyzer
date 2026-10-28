"""Size-limited persistence of uploaded files."""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request, UploadFile

from app.i18n import tr

_CHUNK = 1024 * 1024


def reject_oversized_request(request: Request, max_bytes: int) -> None:
    """Cheap early rejection based on the declared body size."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes + 64 * 1024:  # multipart overhead
        raise HTTPException(status_code=413, detail=_too_large(max_bytes))


def save_upload(upload: UploadFile, dest: Path, max_bytes: int) -> int:
    """Copy an upload to `dest` in chunks, enforcing `max_bytes` on the
    actual content (the declared Content-Length can't be trusted).
    Returns the number of bytes written; removes `dest` on failure."""
    size = 0
    try:
        with open(dest, "wb") as out:
            while chunk := upload.file.read(_CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail=_too_large(max_bytes))
                out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return size


def _too_large(max_bytes: int) -> str:
    return tr("File is too large (limit: {limit} MB).", limit=max_bytes // (1024 * 1024))
