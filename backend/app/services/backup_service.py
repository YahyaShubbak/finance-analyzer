"""Backup and restore.

Backup creation is deliberately decoupled from the app's live SQLAlchemy
session — it uses Python's stdlib `sqlite3` directly, both to take a
*consistent* snapshot (via the sqlite3 backup API, which correctly reads
through any pending WAL data rather than risking a torn copy of the raw
file) and so it can be called safely even during a restore-in-progress
(e.g. to snapshot the current state right before overwriting it).

A backup ZIP contains:
    finance.db      — a consistent snapshot of the whole database
    manifest.json    — created_at, the alembic revision at backup time,
                       and row counts, for basic self-validation
    imports/...      — every original imported source document, so the
                       full raw-source -> raw-transaction -> normalized
                       chain stays traceable after a restore

A backup file may come from anywhere (the restore endpoint accepts
uploads), so it is treated as untrusted input:

* every member name is validated — absolute paths, drive letters,
  backslashes and ``..`` components are rejected (no "zip slip": nothing
  can ever be written outside the imports directory);
* total uncompressed size is capped (zip-bomb guard);
* the database must pass SQLite's integrity check, contain the app's
  tables, and have been written by this or an older app version.

Restore is staged: everything is extracted and the database migrated to
the current schema inside a temporary directory next to the live data
first. Only when that fully succeeded is a safety backup of the current
state taken and the staged files swapped into place — so a corrupt or
truncated backup can never leave the app half-restored.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from app.config import settings
from app.i18n import tr

_REQUIRED_TABLES = {
    "accounts", "imports", "raw_transactions", "transactions", "user_corrections",
    "merchant_rules", "category_rules", "credit_card_statements", "reconciliations",
}

_COUNTED_TABLES = [
    "accounts", "imports", "raw_transactions", "transactions", "user_corrections",
    "merchant_rules", "category_rules", "credit_card_statements", "reconciliations",
]

_IMPORTS_PREFIX = "imports/"
_COPY_CHUNK = 1024 * 1024


class BackupError(Exception):
    pass


class BackupValidationError(BackupError):
    """Raised for an invalid/corrupt backup — current data is guaranteed
    untouched whenever this is raised, since validation always runs
    before any existing file is modified."""


@dataclass
class BackupInfo:
    filename: str
    created_at: str
    size_bytes: int
    counts: dict[str, int]


@dataclass
class RestoreResult:
    restored_from: str
    safety_backup: str
    counts: dict[str, int]


def _snapshot_sqlite_db(source_path: Path, dest_path: Path) -> None:
    """Consistent copy via SQLite's own backup API — safe even while the
    source has pending WAL data, unlike a raw file copy."""
    source_conn = sqlite3.connect(str(source_path))
    try:
        dest_conn = sqlite3.connect(str(dest_path))
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()


def _table_counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(str(db_path))
    try:
        counts = {}
        existing_tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in _COUNTED_TABLES:
            if table in existing_tables:
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            else:
                counts[table] = 0
        return counts
    finally:
        conn.close()


def _current_alembic_revision(db_path: Path) -> str | None:
    conn = sqlite3.connect(str(db_path))
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "alembic_version" not in tables:
            return None
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def create_backup_zip(filename_prefix: str = "finance-backup") -> Path:
    """Creates a timestamped backup ZIP under settings.backups_dir and
    returns its path. Never modifies the live database — only reads a
    consistent snapshot of it."""
    settings.ensure_directories()

    if not settings.database_path.exists():
        raise BackupError(tr("No database found to back up yet."))

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    unique_suffix = uuid.uuid4().hex[:6]
    zip_path = settings.backups_dir / f"{filename_prefix}-{timestamp}-{unique_suffix}.zip"
    partial_path = zip_path.with_suffix(".zip.partial")

    with tempfile.TemporaryDirectory(dir=settings.data_dir) as tmp_dir:
        tmp_db = Path(tmp_dir) / "finance.db"
        _snapshot_sqlite_db(settings.database_path, tmp_db)

        counts = _table_counts(tmp_db)
        imports_files = sorted(f for f in settings.imports_dir.rglob("*") if f.is_file()) \
            if settings.imports_dir.exists() else []

        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "alembic_revision": _current_alembic_revision(tmp_db),
            "counts": counts,
            "imports_file_count": len(imports_files),
        }

        try:
            with zipfile.ZipFile(partial_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(tmp_db, "finance.db")
                zf.writestr("manifest.json", json.dumps(manifest, indent=2))
                for f in imports_files:
                    zf.write(f, _IMPORTS_PREFIX + f.relative_to(settings.imports_dir).as_posix())
            # Only a complete archive ever gets the .zip name, so a crash
            # mid-write can't leave a truncated file that looks restorable.
            os.replace(partial_path, zip_path)
        finally:
            partial_path.unlink(missing_ok=True)

    return zip_path


def _manifest_counts(manifest: dict) -> dict[str, int]:
    """The row counts a manifest lists — only well-formed entries (the
    manifest of a hand-made or damaged file may hold anything)."""
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        return {}
    return {str(k): v for k, v in counts.items() if isinstance(v, int) and not isinstance(v, bool)}


def list_backups() -> list[BackupInfo]:
    """Newest first (by file time — names of safety and manual backups sort differently)."""
    settings.ensure_directories()
    infos = []
    paths = sorted(settings.backups_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in paths:
        try:
            with zipfile.ZipFile(path) as zf:
                manifest = json.loads(zf.read("manifest.json"))
            if not isinstance(manifest, dict):
                continue
            infos.append(BackupInfo(
                filename=path.name,
                created_at=str(manifest.get("created_at") or ""),
                size_bytes=path.stat().st_size,
                counts=_manifest_counts(manifest),
            ))
        except (zipfile.BadZipFile, KeyError, ValueError, OSError):
            continue  # skip unreadable files rather than fail the whole listing
    return infos


def _safe_member_path(name: str) -> PurePosixPath:
    """Validate one ZIP member name and return it as a relative path.
    Anything that could resolve outside the extraction directory is
    rejected outright — the name is never 'cleaned up' and then used."""
    # Checked on the raw string: PurePosixPath would silently collapse "//".
    # ":" covers Windows drive letters ("C:") and alternate data streams.
    raw_parts = name.split("/")
    if (
        not name or name.startswith("/") or any(ch in name for ch in ("\\", "\x00", ":"))
        or any(part in ("", ".", "..") for part in raw_parts)
    ):
        raise BackupValidationError(tr("This backup contains an unsafe file name: {name!r}", name=name))
    return PurePosixPath(name)


def _import_members(zf: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, PurePosixPath]]:
    """(member, path relative to imports/) for every source document."""
    members = []
    for info in zf.infolist():
        if not info.filename.startswith(_IMPORTS_PREFIX) or info.is_dir():
            continue
        relative = _safe_member_path(info.filename).relative_to(_IMPORTS_PREFIX.rstrip("/"))
        members.append((info, relative))
    return members


def validate_backup_zip(zip_path: Path) -> dict:
    """Validates a backup file's structure and database integrity WITHOUT
    touching any current data. Returns the parsed manifest on success;
    raises BackupValidationError with a clear, specific reason on
    failure — current data is never at risk from a failed validation."""
    if not zipfile.is_zipfile(zip_path):
        raise BackupValidationError(tr("This file is not a valid backup archive (not a ZIP file)."))

    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            for info in infos:
                _safe_member_path(info.filename.rstrip("/") if info.is_dir() else info.filename)
            names = {i.filename for i in infos}
            if "finance.db" not in names:
                raise BackupValidationError(tr("This backup is missing its database file (finance.db)."))
            if "manifest.json" not in names:
                raise BackupValidationError(tr("This backup is missing its manifest (manifest.json)."))

            total_size = sum(i.file_size for i in infos)
            if total_size > settings.max_backup_uncompressed_bytes:
                raise BackupValidationError(tr(
                    "This backup would unpack to {size} MB, which exceeds the limit of {limit} MB.",
                    size=total_size // (1024 * 1024), limit=settings.max_backup_uncompressed_bytes // (1024 * 1024),
                ))

            try:
                manifest = json.loads(zf.read("manifest.json"))
            except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
                raise BackupValidationError(tr("This backup's manifest is corrupt: {error}", error=exc)) from exc
            if not isinstance(manifest, dict):
                raise BackupValidationError(tr("This backup's manifest is corrupt: not a JSON object."))

            with tempfile.TemporaryDirectory(dir=settings.data_dir) as tmp_dir:
                tmp_db = Path(tmp_dir) / "finance.db"
                with zf.open("finance.db") as src, open(tmp_db, "wb") as dst:
                    shutil.copyfileobj(src, dst, _COPY_CHUNK)
                _validate_database_file(tmp_db)
    except zipfile.BadZipFile as exc:
        raise BackupValidationError(tr("This backup archive is damaged: {error}", error=exc)) from exc

    return manifest


def _validate_database_file(db_path: Path) -> None:
    from app.db.migrate import known_revisions

    try:
        conn = sqlite3.connect(str(db_path))
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise BackupValidationError(tr("This backup's database failed an integrity check: {integrity}", integrity=integrity))
            existing_tables = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            # the app's schema has no triggers or views: such code would run on every later
            # write (e.g. change amounts silently) — the file was changed outside the app
            if conn.execute("SELECT count(*) FROM sqlite_master WHERE type IN ('trigger', 'view')").fetchone()[0]:
                raise BackupValidationError(tr(
                    "This backup's database contains code the app never creates (triggers or views); "
                    "it was changed outside the app and is not restored."))
            missing = _REQUIRED_TABLES - existing_tables
            if missing:
                raise BackupValidationError(tr("This backup's database is missing expected tables: {tables}",
                                                tables=", ".join(sorted(missing))))
            if "alembic_version" in existing_tables:
                row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
                if row and row[0] not in known_revisions():
                    raise BackupValidationError(tr(
                        "This backup was created by a newer version of the app. "
                        "Update the app, then restore it again."
                    ))
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise BackupValidationError(
            tr("This backup's database file is corrupt or not a valid SQLite database: {error}", error=exc)
        ) from exc


def _stage_restore(zip_path: Path, staging_root: Path) -> tuple[Path, Path]:
    """Extract and migrate the backup inside `staging_root`. Returns the
    staged (database, imports directory)."""
    from app.db.migrate import upgrade_database

    staged_db = staging_root / "finance.db"
    staged_imports = staging_root / "imports"
    staged_imports.mkdir(parents=True)
    staged_imports_resolved = staged_imports.resolve()

    try:
        with zipfile.ZipFile(zip_path) as zf:
            with zf.open("finance.db") as src, open(staged_db, "wb") as dst:
                shutil.copyfileobj(src, dst, _COPY_CHUNK)
            for info, relative in _import_members(zf):
                target = staged_imports / Path(*relative.parts)
                # Defence in depth on top of _safe_member_path.
                if not target.resolve().is_relative_to(staged_imports_resolved):
                    raise BackupValidationError(tr("This backup contains an unsafe file name: {name!r}", name=info.filename))
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, _COPY_CHUNK)
    except (zipfile.BadZipFile, EOFError) as exc:
        # CRC mismatches surface here, while reading — before anything live is touched.
        raise BackupValidationError(tr("This backup archive is damaged: {error}", error=exc)) from exc
    except OSError as exc:
        # e.g. a file name too long for this system, or a file and a folder of the same name
        raise BackupValidationError(tr("This backup's files can't be unpacked here: {error}", error=exc.strerror or exc)) from exc

    try:
        upgrade_database(staged_db)
    except Exception as exc:  # noqa: BLE001 — any failure means "don't restore this"
        raise BackupValidationError(tr("This backup's database could not be upgraded to the current version: {error}", error=exc)) from exc

    return staged_db, staged_imports


def restore_from_backup(zip_path: Path, confirm: bool) -> RestoreResult:
    """Restores the database and imported source documents from a backup
    ZIP. Requires explicit confirmation. Current data is untouched unless
    the backup was fully validated, extracted and migrated. Takes an
    automatic safety backup of the current state immediately before
    swapping the restored files in.
    """
    if not confirm:
        raise BackupError(tr("Restore requires explicit confirmation."))

    from app.db import session as db_session

    with db_session.maintenance_lock:
        manifest = validate_backup_zip(zip_path)  # raises before anything is touched
        settings.ensure_directories()

        staging_root = settings.data_dir / f".restore-{uuid.uuid4().hex}"
        staging_root.mkdir()
        try:
            staged_db, staged_imports = _stage_restore(zip_path, staging_root)

            safety_backup_path = None
            if settings.database_path.exists():
                safety_backup_path = create_backup_zip(filename_prefix="pre-restore-safety")

            # Close pooled connections to the current database before
            # replacing the file out from under them.
            db_session.engine.dispose()

            try:
                # Remove WAL/SHM sidecars so the restored database isn't
                # merged with stale WAL data from the old one.
                for suffix in ("-wal", "-shm"):
                    Path(str(settings.database_path) + suffix).unlink(missing_ok=True)
                os.replace(staged_db, settings.database_path)

                # shutil.move: the imports directory may be configured on a
                # different file system than the data directory.
                previous_imports = staging_root / "imports.previous"
                if settings.imports_dir.exists():
                    shutil.move(settings.imports_dir, previous_imports)
                shutil.move(staged_imports, settings.imports_dir)
            except OSError as exc:
                hint = (" " + tr("Your previous data is saved in {file}.", file=safety_backup_path.name)
                        if safety_backup_path else "")
                raise BackupError(tr("Restore failed while replacing files: {error}.", error=exc) + hint) from exc
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)

        # an older backup lacks what newer versions work out on start-up
        from app.services.location_service import refresh_outdated_locations
        from app.services.points_service import backfill_points
        from app.services.transfer_marking import link_card_bills, settle_flagged_transfers
        with db_session.session_scope() as session:
            refresh_outdated_locations(session)
            settle_flagged_transfers(session)
            link_card_bills(session)
            backfill_points(session, force=True)
            from app.services.statement_refresh import refresh_statement_totals

            refresh_statement_totals(session, force=True)
            from app.services.account_recognition import refresh_signatures

            refresh_signatures(session, force=True)
            # the restored bookings may predate the current built-in rules
            from app.services.rule_service import RULES_MARKER, apply_rule_updates

            (settings.data_dir / RULES_MARKER).unlink(missing_ok=True)
            apply_rule_updates(session)
            from app.services.twin_merge import merge_cross_file_twins

            merge_cross_file_twins(session, force=True)

    return RestoreResult(
        restored_from=zip_path.name,
        safety_backup=safety_backup_path.name if safety_backup_path else "",
        counts=_manifest_counts(manifest),
    )


def purge_leftover_restore_dirs() -> None:
    """On start-up: folders a restore or backup interrupted by a crash left
    behind (each may hold a full copy of the database)."""
    for path in settings.data_dir.glob(".restore-*"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    for path in settings.data_dir.glob("tmp*"):
        if path.is_dir() and (path / "finance.db").exists():
            shutil.rmtree(path, ignore_errors=True)
