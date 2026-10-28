"""Start over: every booking, import, account, category, rule, budget and
point is deleted, with the stored originals and exports. Backups stay
unless asked — they are the way back."""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, SQLModel, delete

from app.config import settings

logger = logging.getLogger("finance")



@dataclass
class ResetResult:
    rows_deleted: int
    files_deleted: int


def _empty_folder(folder: Path) -> int:
    """Delete what is inside `folder` (the folder itself stays)."""
    if not folder.exists():
        return 0
    count = 0
    for child in folder.iterdir():
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
            count += 1
        except OSError:
            logger.warning("Could not delete %s during the reset", child.name)
    return count


def reset_everything(session: Session, delete_backups: bool = False) -> ResetResult:
    rows = 0
    for table in reversed(SQLModel.metadata.sorted_tables):  # dependents first
        rows += session.exec(delete(table)).rowcount or 0
    session.commit()
    session.close()
    # deleted rows must not stay readable in the database file (VACUUM needs autocommit)
    from app.db.session import engine

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql("VACUUM")
        connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")

    files = sum(_empty_folder(folder) for folder in (settings.imports_dir, settings.exports_dir, settings.staging_dir))
    if delete_backups:
        files += _empty_folder(settings.backups_dir)
    # start-up work a fresh database needs again
    from app.services.account_recognition import SIGNATURES_MARKER
    from app.services.points_service import POINTS_MARKER
    from app.services.rule_service import RULES_MARKER
    from app.services.statement_refresh import STATEMENTS_MARKER
    from app.services.twin_merge import TWINS_MARKER

    for marker in (RULES_MARKER, POINTS_MARKER, STATEMENTS_MARKER, SIGNATURES_MARKER, TWINS_MARKER):
        (settings.data_dir / marker).unlink(missing_ok=True)

    # the built-in rules come back at once (user-made ones are gone)
    from app.db.session import session_scope
    from app.normalization.category import sync_default_category_rules
    from app.normalization.merchant import sync_default_merchant_rules

    with session_scope() as fresh:
        sync_default_merchant_rules(fresh)
        sync_default_category_rules(fresh)
    logger.info("Reset: %d rows and %d files deleted", rows, files)
    return ResetResult(rows_deleted=rows, files_deleted=files)
