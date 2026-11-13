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

The swap itself is all or nothing as well (see _swap_in): the current
database and documents are moved aside, not overwritten, and moved back
if any step fails — e.g. a document that is open in another program — so
a restored database never ends up next to the previous documents.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from app.config import settings
from app.db import session as db_session
from app.db.migrate import known_revisions, upgrade_database
from app.i18n import tr
from app.services.account_recognition import refresh_signatures
from app.services.card_bill_linking import link_card_bills
from app.services.import_staging import is_app_document, stored_relative_name
from app.services.location_service import refresh_outdated_locations
from app.services.points_service import backfill_points
from app.services.rule_service import RULES_MARKER, apply_rule_updates
from app.services.statement_refresh import refresh_statement_totals
from app.services.transfer_marking import settle_flagged_transfers
from app.services.twin_merge import merge_cross_file_twins

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
#: inside the staging folder of a restore: the database and documents it replaced
_PREVIOUS = "previous"
#: the working folders of a backup or a validation in the data folder (each holds a copy of the database)
_TMP_PREFIX = ".finance-tmp-"

logger = logging.getLogger("finance")


#: the backups made by the app right before a restore: their name, and how many are kept
SAFETY_PREFIX = "pre-restore-safety"
SAFETY_BACKUPS_KEPT = 3


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

    with tempfile.TemporaryDirectory(dir=settings.data_dir, prefix=_TMP_PREFIX) as tmp_dir:
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


def is_backup_zip(path: Path) -> bool:
    """A backup of this app — also one put into the backups folder by hand:
    a ZIP holding a database and a manifest. Anything else in that folder
    (it may be a shared or synced one) is not the app's to list or delete."""
    if path.suffix.lower() != ".zip":
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            return {"finance.db", "manifest.json"} <= set(archive.namelist())
    except (zipfile.BadZipFile, OSError):
        return False


def delete_backup(path: Path) -> None:
    """Removes one backup for good."""
    if not is_backup_zip(path):
        raise BackupError(tr("Backup not found."))
    try:
        path.unlink()
    except OSError as exc:
        raise BackupError(tr("The backup could not be deleted: {error}", error=exc.strerror or type(exc).__name__)) from exc


def _prune_safety_backups() -> None:
    """Every restore leaves a full backup of the state before it — each
    with every original document. Kept without limit they fill the disk;
    the newest SAFETY_BACKUPS_KEPT stay. (Backups the user made are never
    removed here.)"""
    copies = sorted(settings.backups_dir.glob(f"{SAFETY_PREFIX}-*.zip"), key=lambda path: path.stat().st_mtime)
    for old in copies[:-SAFETY_BACKUPS_KEPT]:
        try:
            old.unlink()
        except OSError:
            logger.warning("Could not remove the old safety backup %s", old.name)


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

            with tempfile.TemporaryDirectory(dir=settings.data_dir, prefix=_TMP_PREFIX) as tmp_dir:
                tmp_db = Path(tmp_dir) / "finance.db"
                with zf.open("finance.db") as src, open(tmp_db, "wb") as dst:
                    shutil.copyfileobj(src, dst, _COPY_CHUNK)
                _validate_database_file(tmp_db)
    except zipfile.BadZipFile as exc:
        raise BackupValidationError(tr("This backup archive is damaged: {error}", error=exc)) from exc

    return manifest


def _validate_database_file(db_path: Path) -> None:
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


class _SwapError(Exception):
    """The restored files could not be put in place. `put_back`: the
    previous database and documents are where they were again."""

    def __init__(self, cause: OSError, put_back: bool):
        super().__init__(str(cause))
        self.cause = cause
        self.put_back = put_back


def _put_folder_back(saved: Path, original: Path) -> None:
    if not saved.exists():
        return
    if original.exists():
        # partly there — a move to another file system that stopped half-way: fill in what is missing
        shutil.copytree(saved, original, dirs_exist_ok=True)
    else:
        shutil.move(saved, original)


def _swap_in(staged_db: Path, staged_imports: Path, staging_root: Path) -> None:
    """Put the staged database and documents in place of the current ones —
    both, or neither. What is replaced is moved to `staging_root/previous`
    first; when a step fails, the steps already taken are undone in reverse.
    The documents go first: they are the step most likely to fail (a file
    open in a viewer, a folder on another drive), while the database is
    still untouched.

    Raises _SwapError; pooled connections to the database must be closed."""
    database, imports = settings.database_path, settings.imports_dir
    # With its WAL/SHM sidecars: the restored database must not be merged
    # with the pending WAL data of the old one — which needs them back.
    database_files = [database, Path(f"{database}-wal"), Path(f"{database}-shm")]
    previous = staging_root / _PREVIOUS
    previous.mkdir()

    def put_database_back() -> None:
        for f in database_files:
            if (previous / f.name).exists():
                os.replace(previous / f.name, f)

    def remove_restored_documents() -> None:
        if imports.exists():
            shutil.rmtree(imports)

    undo: list[Callable[[], None]] = []  # each registered BEFORE its step: a step may fail half-way
    try:
        undo.append(lambda: _put_folder_back(previous / "imports", imports))
        if imports.exists():
            # shutil.move: the imports directory may be configured on a
            # different file system than the data directory.
            shutil.move(imports, previous / "imports")
        # (from here on, whatever is at `imports` belongs to the restored backup)
        undo.append(remove_restored_documents)
        shutil.move(staged_imports, imports)

        undo.append(put_database_back)
        for f in database_files:
            if f.exists():
                os.replace(f, previous / f.name)
        os.replace(staged_db, database)
    except OSError as exc:
        put_back = True
        for step in reversed(undo):
            try:
                step()
            except OSError:
                put_back = False
                logger.exception("Could not undo a step of the failed restore")
        raise _SwapError(exc, put_back) from exc


def _stored_document_names(database_path: Path) -> set[str]:
    """The stored originals of the imports in this database, as names
    inside the imports folder. Empty when it can't be read (then only files
    named the way the app names them count as the app's)."""
    if not database_path.exists():
        return set()
    try:
        conn = sqlite3.connect(str(database_path))
        try:
            return {stored_relative_name(row[0]) for row in conn.execute("SELECT stored_path FROM imports")}
        finally:
            conn.close()
    except sqlite3.Error:
        return set()


def _keep_other_files(replaced: Path, imports: Path, app_documents: set[str]) -> bool:
    """The imports folder may be one the user also keeps other files in
    (FINANCE_IMPORTS_DIR pointing at an archive of statements, say). The
    restore replaced the folder as a whole; whatever in the replaced one was
    not an import's stored original is moved back, so only the app's own
    documents go. Returns False if a file could not be moved — it then
    stays in `replaced`."""
    if not replaced.is_dir():
        return True
    complete = True
    for path in sorted(replaced.rglob("*")):
        relative = path.relative_to(replaced)
        if not path.is_file() or is_app_document(relative, app_documents):
            continue
        target = imports / relative
        if target.exists():
            continue  # the backup holds a file of that name: the same document
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(path, target)
        except OSError:
            complete = False
            logger.exception("Could not move %s back to the imports folder; it stays in %s", relative, replaced)
    return complete


def restore_from_backup(zip_path: Path, confirm: bool) -> RestoreResult:
    """Restores the database and imported source documents from a backup
    ZIP. Requires explicit confirmation. Current data is untouched unless
    the backup was fully validated, extracted and migrated. Takes an
    automatic safety backup of the current state immediately before
    swapping the restored files in.
    """
    if not confirm:
        raise BackupError(tr("Restore requires explicit confirmation."))

    with db_session.maintenance_lock:
        manifest = validate_backup_zip(zip_path)  # raises before anything is touched
        settings.ensure_directories()

        staging_root = settings.data_dir / f".restore-{uuid.uuid4().hex}"
        staging_root.mkdir()
        keep_staging = False
        try:
            staged_db, staged_imports = _stage_restore(zip_path, staging_root)

            safety_backup_path = None
            if settings.database_path.exists():
                safety_backup_path = create_backup_zip(filename_prefix=SAFETY_PREFIX)
                _prune_safety_backups()
            replaced_documents = _stored_document_names(settings.database_path)

            # Close pooled connections to the current database before
            # replacing the file out from under them.
            db_session.engine.dispose()

            try:
                _swap_in(staged_db, staged_imports, staging_root)
            except _SwapError as exc:
                failed = tr("Restore failed while replacing files: {error}.", error=exc.cause)
                if exc.put_back:
                    raise BackupError(failed + " " + tr("Nothing was changed: your data is as it was before.")) from exc
                # What was replaced stays where it was moved to (purge_leftover_restore_dirs leaves it alone).
                keep_staging = True
                hint = (" " + tr("Your previous data is saved in {file}.", file=safety_backup_path.name)
                        if safety_backup_path else "")
                raise BackupError(failed + " " + tr(
                    "Your data could not be put back completely. Stop the app; what was there before is in "
                    "the folder {folder}.", folder=staging_root / _PREVIOUS) + hint) from exc
            db_session.note_data_changed()  # another database now: nothing remembered about the data holds
            # The restore is done. What else lay in the imports folder goes back there.
            if not _keep_other_files(staging_root / _PREVIOUS / "imports", settings.imports_dir, replaced_documents):
                keep_staging = True  # named in the log, and again on every start-up until it is dealt with
        finally:
            if not keep_staging:
                shutil.rmtree(staging_root, ignore_errors=True)

        # an older backup lacks what newer versions work out on start-up
        with db_session.session_scope() as session:
            refresh_outdated_locations(session)
            settle_flagged_transfers(session)
            link_card_bills(session)
            backfill_points(session, force=True)
            refresh_statement_totals(session, force=True)
            refresh_signatures(session, force=True)
            # the restored bookings may predate the current built-in rules
            (settings.data_dir / RULES_MARKER).unlink(missing_ok=True)
            apply_rule_updates(session)
            merge_cross_file_twins(session, force=True)

    return RestoreResult(
        restored_from=zip_path.name,
        safety_backup=safety_backup_path.name if safety_backup_path else "",
        counts=_manifest_counts(manifest),
    )


def purge_leftover_restore_dirs() -> None:
    """On start-up: folders a restore or backup interrupted by a crash left
    behind (each may hold a full copy of the database). A restore that
    stopped while replacing files — or could not undo that — still holds the
    database and documents it was replacing: that folder stays, and is named."""
    for path in settings.data_dir.glob(".restore-*"):
        if not path.is_dir():
            continue
        previous = path / _PREVIOUS
        if previous.is_dir() and any(previous.iterdir()):
            logger.warning(
                "A restore did not finish. The database and documents it was replacing are kept in %s — "
                "check your data, then delete that folder.", previous,
            )
            continue
        shutil.rmtree(path, ignore_errors=True)
    # (only folders with the app's own prefix: a "tmp..." folder holding a
    # finance.db may be a copy the user put there)
    for path in settings.data_dir.glob(f"{_TMP_PREFIX}*"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
