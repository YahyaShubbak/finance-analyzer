"""Start over: every booking, import, account, category, rule, budget and
point is deleted, with the stored originals and exports. Backups stay
unless asked — they are the way back.

Only the app's own files are deleted. The imports and backups folders can
be set to any folder (FINANCE_IMPORTS_DIR, FINANCE_BACKUPS_DIR) — one the
user also keeps other things in, say an archive of statements or a shared
drive: what the app did not put there is not the app's to delete.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, SQLModel, delete, select, update

from app.config import settings
from app.db.models import ImportRecord, RawTransaction
from app.db.session import session_scope
from app.normalization.category import sync_default_category_rules
from app.normalization.merchant import sync_default_merchant_rules
from app.services.account_recognition import SIGNATURES_MARKER
from app.services.backup_service import is_backup_zip
from app.services.import_staging import is_app_document, stored_relative_name
from app.services.points_service import POINTS_MARKER
from app.services.rule_service import RULES_MARKER
from app.services.statement_refresh import STATEMENTS_MARKER
from app.services.twin_merge import TWINS_MARKER

logger = logging.getLogger("finance")

# What the app names the files it writes to the backups folder.
_BACKUP_PREFIXES = ("finance-backup-", "pre-restore-safety-", "pre-upgrade-")


@dataclass
class ResetResult:
    rows_deleted: int
    files_deleted: int


def _delete(path: Path) -> int:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
        return 1
    except OSError:
        logger.warning("Could not delete %s during the reset", path.name)
        return 0


def _empty_folder(folder: Path) -> int:
    """Delete what is inside `folder` (the folder itself stays) — for
    folders that are the app's alone."""
    if not folder.exists():
        return 0
    return sum(_delete(child) for child in folder.iterdir())


def _delete_stored_documents(stored_paths: set[str]) -> int:
    """The imports' stored originals (and copies left by imports that
    failed); other files in the folder stay."""
    folder = settings.imports_dir
    if not folder.exists():
        return 0
    return sum(
        _delete(path) for path in sorted(folder.rglob("*"))
        if path.is_file() and is_app_document(path.relative_to(folder), stored_paths)
    )


def _is_backup(path: Path) -> bool:
    """A file the app wrote to the backups folder, or a backup put there by
    hand (as Settings lists it): a ZIP holding a database and a manifest."""
    return path.name.startswith(_BACKUP_PREFIXES) or is_backup_zip(path)


def _delete_backups() -> int:
    folder = settings.backups_dir
    if not folder.exists():
        return 0
    return sum(_delete(path) for path in sorted(folder.iterdir()) if path.is_file() and _is_backup(path))


def reset_everything(session: Session, delete_backups: bool = False) -> ResetResult:
    # (known only while the imports are still in the database)
    stored_paths = {stored_relative_name(path) for path in session.exec(select(ImportRecord.stored_path)).all()}

    rows = 0
    # (the one reference that goes against the tables' order: a skipped row's booking)
    session.exec(update(RawTransaction).values(duplicate_of_transaction_id=None))
    for table in reversed(SQLModel.metadata.sorted_tables):  # dependents first
        rows += session.exec(delete(table)).rowcount or 0
    session.commit()
    session.close()
    # deleted rows must not stay readable in the database file (VACUUM needs autocommit)
    from app.db.session import engine

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql("VACUUM")
        connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")

    files = _delete_stored_documents(stored_paths) + _empty_folder(settings.staging_dir)
    # The app writes no exports; the folder is emptied only where it is the
    # app's own (inside the data folder), never one configured elsewhere.
    if settings.exports_dir.resolve().is_relative_to(settings.data_dir.resolve()):
        files += _empty_folder(settings.exports_dir)
    if delete_backups:
        files += _delete_backups()
    # start-up work a fresh database needs again
    for marker in (RULES_MARKER, POINTS_MARKER, STATEMENTS_MARKER, SIGNATURES_MARKER, TWINS_MARKER):
        (settings.data_dir / marker).unlink(missing_ok=True)

    # the built-in rules come back at once (user-made ones are gone)
    with session_scope() as fresh:
        sync_default_merchant_rules(fresh)
        sync_default_category_rules(fresh)
    logger.info("Reset: %d rows and %d files deleted", rows, files)
    return ResetResult(rows_deleted=rows, files_deleted=files)
