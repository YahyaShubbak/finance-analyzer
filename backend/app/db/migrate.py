"""Runs Alembic migrations programmatically — `alembic upgrade head` is the
single source of truth for schema state, whether this is a brand-new
install (migrations create every table from scratch), an existing
database (migrations apply only the incremental changes, in place,
preserving all data), or a restored backup from an older version.
"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.config import REPO_ROOT, settings

_BACKEND_DIR = REPO_ROOT / "backend"
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"
_MIGRATIONS_DIR = _BACKEND_DIR / "app" / "db" / "migrations"

# Revisions of the migration chain whose schema a pre-Alembic database may
# match (see _detect_unversioned_revision). Newest first. Every new
# migration must add its own check to _detect_unversioned_revision.
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


def upgrade_database(database_path: Path) -> None:
    """Migrate the SQLite database at `database_path` to the latest schema."""
    database_url = f"sqlite:///{database_path}"
    cfg = _alembic_config(database_url)

    probe_engine = create_engine(database_url)
    try:
        inspector = inspect(probe_engine)
        existing_tables = set(inspector.get_table_names())
        stamp_revision = None
        if "accounts" in existing_tables and "alembic_version" not in existing_tables:
            stamp_revision = _detect_unversioned_revision(inspector)
    finally:
        probe_engine.dispose()

    if stamp_revision is not None:
        command.stamp(cfg, stamp_revision)
    command.upgrade(cfg, "head")


def run_migrations_to_head() -> None:
    settings.ensure_directories()
    upgrade_database(settings.database_path)
