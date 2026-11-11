"""Runs Alembic migrations programmatically — `alembic upgrade head` is the
single source of truth for schema state, whether this is a brand-new
install (migrations create every table from scratch), an existing
database (migrations apply only the incremental changes, in place,
preserving all data), or a restored backup from an older version.

Before the app's own database is upgraded it is copied to the backups
folder (``pre-upgrade-<revision>-<time>.db``): SQLite can't undo a schema
change that stopped half-way (a full disk, the window closed, the process
killed), and a database left like that fails every later upgrade.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.config import REPO_ROOT, settings

logger = logging.getLogger("finance")

#: the copies of the database made before a schema upgrade: their name, and how many are kept
PRE_UPGRADE_PREFIX = "pre-upgrade-"
PRE_UPGRADE_COPIES_KEPT = 3

_BACKEND_DIR = REPO_ROOT / "backend"
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"
_MIGRATIONS_DIR = _BACKEND_DIR / "app" / "db" / "migrations"

# Revisions of the migration chain whose schema a pre-Alembic database may
# match (see _detect_unversioned_revision). Newest first. Every new
# migration must add its own check to _detect_unversioned_revision.
_REV_IMPORT_IDS = "e3a91f5c7d08"
_REV_POINTS = "b7d3e9a41c52"
_REV_IMPORT_SOURCE = "9c2e7d4b1f30"
_REV_TRANSACTION_LOCATION = "5be3c1f0a7d2"
_REV_CUSTOM_CATEGORIES = "d41b7c9e2a65"
_REV_SETTLEMENT_LINK = "8a56f61e98ab"
_REV_BUDGETS = "c572d7080be2"
_REV_OPENING_BALANCE = "44ad620a3645"
_REV_NEEDS_REVIEW = "0f1597c97f2c"
_REV_USER_RESOLUTION_TAGS = "c8b446ce5dd9"
_REV_INITIAL = "68438a4a1e4b"


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def known_revisions() -> set[str]:
    script = ScriptDirectory.from_config(_alembic_config(settings.database_url))
    return {rev.revision for rev in script.walk_revisions()}


def _detect_unversioned_revision(inspector) -> str:
    """Databases created before Alembic was wired up were built with
    SQLModel.metadata.create_all, i.e. they match whatever models.py looked
    like at that time — which may be older than the newest migration.
    Stamping such a database as "head" would silently skip the migrations
    it is actually missing, so identify the newest revision whose schema
    changes are present, stamp that, and let `upgrade` apply the rest."""
    tables = set(inspector.get_table_names())

    def columns(table: str) -> set[str]:
        return {c["name"] for c in inspector.get_columns(table)} if table in tables else set()

    if _has_autoincrement(inspector, "imports"):
        return _REV_IMPORT_IDS
    if "points_entries" in tables:
        return _REV_POINTS
    if "source_key" in columns("imports"):
        return _REV_IMPORT_SOURCE
    if "location_version" in columns("transactions"):
        return _REV_TRANSACTION_LOCATION
    if "custom_categories" in tables:
        return _REV_CUSTOM_CATEGORIES
    if "settles_statement_id" in columns("transactions"):
        return _REV_SETTLEMENT_LINK
    if "budgets" in tables:
        return _REV_BUDGETS
    if "opening_balance_minor" in columns("accounts"):
        return _REV_OPENING_BALANCE
    if "needs_review" in columns("transactions"):
        return _REV_NEEDS_REVIEW
    if "user_resolution_tags_json" in columns("reconciliations"):
        return _REV_USER_RESOLUTION_TAGS
    return _REV_INITIAL


def _has_autoincrement(inspector, table: str) -> bool:
    """(Not part of what the inspector reflects: read from the table's definition.)"""
    with inspector.bind.connect() as connection:
        definition = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).scalar()
    return "AUTOINCREMENT" in (definition or "").upper()


def _schema_revision(database_path: Path) -> tuple[str | None, bool]:
    """(the revision the database's schema is at, whether it still has to be
    stamped with it — a database from before Alembic). None: a new, empty
    database."""
    probe_engine = create_engine(f"sqlite:///{database_path}")
    try:
        inspector = inspect(probe_engine)
        existing_tables = set(inspector.get_table_names())
        if "alembic_version" in existing_tables:
            with probe_engine.connect() as connection:
                return connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar(), False
        if "accounts" in existing_tables:
            return _detect_unversioned_revision(inspector), True
        return None, False
    finally:
        probe_engine.dispose()


def upgrade_database(database_path: Path) -> None:
    """Migrate the SQLite database at `database_path` to the latest schema."""
    cfg = _alembic_config(f"sqlite:///{database_path}")
    revision, unversioned = _schema_revision(database_path)
    if unversioned:
        command.stamp(cfg, revision)
    command.upgrade(cfg, "head")


def _copy_before_upgrade(database_path: Path, revision: str) -> Path:
    """A consistent copy of the database (SQLite's backup API reads through
    pending WAL data) in the backups folder, checked before it counts.
    Older such copies are removed, the newest PRE_UPGRADE_COPIES_KEPT stay."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = settings.backups_dir / f"{PRE_UPGRADE_PREFIX}{revision}-{stamp}.db"
    partial = target.with_name(target.name + ".partial")
    try:
        settings.backups_dir.mkdir(parents=True, exist_ok=True)
        partial.unlink(missing_ok=True)
        source = sqlite3.connect(str(database_path))
        try:
            copy = sqlite3.connect(str(partial))
            try:
                source.backup(copy)
                integrity = copy.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                copy.close()
        finally:
            source.close()
        if integrity != "ok":
            raise sqlite3.DatabaseError(f"integrity check of the copy: {integrity}")
        # only a complete, checked copy gets the name
        os.replace(partial, target)
    except (OSError, sqlite3.Error) as exc:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass  # the folder itself can't be used
        raise RuntimeError(
            f"The database {database_path} has to be upgraded for this version of the app, but it could not be "
            f"copied to {settings.backups_dir} first ({exc}). Nothing was changed. Make room on the disk (or check "
            "that the backups folder can be written to) and start the app again."
        ) from exc

    copies = sorted(settings.backups_dir.glob(f"{PRE_UPGRADE_PREFIX}*.db"), key=lambda path: path.stat().st_mtime)
    for old in copies[:-PRE_UPGRADE_COPIES_KEPT]:
        try:
            old.unlink()
        except OSError:
            pass  # e.g. open in another program: removed after a later upgrade
    return target


def run_migrations_to_head() -> None:
    """The app's own database, on start-up. Copied first when its schema
    is about to change (not for a new database, nor one that is up to date)."""
    settings.ensure_directories()
    database_path = settings.database_path
    revision, _unversioned = _schema_revision(database_path)
    head = ScriptDirectory.from_config(_alembic_config(settings.database_url)).get_current_head()
    copy = _copy_before_upgrade(database_path, revision) if revision is not None and revision != head else None
    try:
        upgrade_database(database_path)
    except Exception:
        if copy is not None:
            logger.error(
                "The database could not be upgraded for this version of the app. It was copied before the "
                "upgrade: %s. To go back, stop the app, install its previous version and put that copy in "
                "place of %s.", copy, database_path,
            )
        raise
    if copy is not None:
        logger.info("Database upgraded; a copy from before the upgrade is kept at %s", copy)
