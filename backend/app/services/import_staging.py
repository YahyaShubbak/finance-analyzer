"""Staging area for uploaded files between preview and commit.

A preview writes the upload to ``<data_dir>/.staging/<id>__<name>`` plus a
``<id>.options.json`` sidecar holding the user's parse options, so the
commit re-parses the exact same bytes with the exact same options. Staged
files hold full bank statements, so abandoned previews are purged after
``settings.staging_max_age_hours``.

Staging ids are server-generated UUID hex strings and are validated
strictly before they touch the file system — a client-supplied id like
``../../x`` or ``*`` must never select an arbitrary file.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from app.config import settings
from app.i18n import tr
from app.importers.base import ParseOptions

STAGING_ID_PATTERN = r"^[0-9a-f]{32}$"
_STAGING_ID_RE = re.compile(STAGING_ID_PATTERN)
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class StagingError(Exception):
    pass


def sanitize_filename(name: str) -> str:
    """A safe file name that keeps its extension (the importer is chosen by
    it): "....csv" -> "upload.csv", a 300-character name -> 120 characters."""
    name = Path(name.replace("\\", "/")).name  # strip any path components
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        stem, suffix = name, ""
    stem = _SAFE_NAME_RE.sub("_", stem).strip("._") or "upload"
    suffix = _SAFE_NAME_RE.sub("", suffix)[:10].lower()
    return f"{stem[:110]}.{suffix}" if suffix else stem[:120]


def new_staging_id() -> str:
    return uuid.uuid4().hex


def _check_id(staging_id: str) -> None:
    if not _STAGING_ID_RE.fullmatch(staging_id or ""):
        raise StagingError(tr("Invalid staging id."))


def staged_file_path(staging_id: str, filename: str) -> Path:
    _check_id(staging_id)
    return settings.staging_dir / f"{staging_id}__{sanitize_filename(filename)}"


def find_staged_file(staging_id: str) -> Path:
    _check_id(staging_id)
    for path in settings.staging_dir.glob(f"{staging_id}__*"):
        if path.is_file():
            return path
    raise StagingError(tr("Preview not found or has expired. Please re-upload the file."))


def save_display_name(staging_id: str, name: str) -> None:
    """The file's name as the user knows it ("März (1).pdf") — shown in the
    import history; the staged file itself gets a safe name."""
    _check_id(staging_id)
    clean = "".join(ch for ch in Path(name.replace("\\", "/")).name if ch.isprintable())[:200]
    if clean:
        (settings.staging_dir / f"{staging_id}.name.txt").write_text(clean, encoding="utf-8")


def original_filename(staged_path: Path) -> str:
    staging_id, _, safe_name = staged_path.name.partition("__")
    sidecar = staged_path.with_name(f"{staging_id}.name.txt")
    try:
        return sidecar.read_text(encoding="utf-8") or safe_name
    except OSError:
        return safe_name


def _options_path(staging_id: str) -> Path:
    _check_id(staging_id)
    return settings.staging_dir / f"{staging_id}.options.json"


def save_options(staging_id: str, options: ParseOptions) -> None:
    _options_path(staging_id).write_text(json.dumps(options.to_dict()), encoding="utf-8")


def load_options(staging_id: str) -> ParseOptions:
    path = _options_path(staging_id)
    if not path.exists():
        return ParseOptions()
    return ParseOptions.from_dict(json.loads(path.read_text(encoding="utf-8")))


def discard(staging_id: str) -> None:
    _check_id(staging_id)
    for path in settings.staging_dir.glob(f"{staging_id}*"):
        path.unlink(missing_ok=True)


def purge_stale_staging_files() -> int:
    """Delete staged uploads older than the configured maximum age."""
    if not settings.staging_dir.exists():
        return 0
    cutoff = time.time() - settings.staging_max_age_hours * 3600
    removed = 0
    for path in settings.staging_dir.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue  # e.g. file in use on Windows — try again next time
    return removed


def stored_import_path(stored_path: str) -> Path | None:
    """Absolute path of an imported source document, or None if the stored
    value would point outside the imports directory. Older versions stored
    "imports/<name>" relative to the repository; newer ones just "<name>"."""
    if not stored_path:
        return None
    name = stored_path.replace("\\", "/")
    if name.startswith("imports/"):
        name = name[len("imports/"):]
    root = settings.imports_dir.resolve()
    candidate = (root / name).resolve()
    return candidate if candidate.is_relative_to(root) and candidate != root else None
