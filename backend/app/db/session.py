"""SQLite engine + session management.

The database is the persistent source of truth. We enable WAL mode and
foreign key enforcement, and never drop/recreate the database on schema
change — migrations are handled via Alembic.
"""
from __future__ import annotations

import threading
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from app.config import settings

# Serializes the few multi-step operations that must never interleave
# (committing an import, restoring a backup, a full transfer re-scan) —
# e.g. two browser tabs committing the same staged file at once. The app
# runs as a single process, so an in-process lock is sufficient.
maintenance_lock = threading.RLock()


def _build_engine():
    # No directory creation here: importing this module must not have side
    # effects on the file system. Directories are created at startup.
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        # deleted bank data is overwritten in the file, not just marked free (removed imports, reset)
        cursor.execute("PRAGMA secure_delete=ON")
        cursor.close()

    return engine


_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def fold_text(value: str | None) -> str | None:
    """Spelling-insensitive form for searching: "BÄCKEREI" and "Baeckerei"
    both become "baeckerei"."""
    return value.lower().translate(_FOLD) if value is not None else None


def fold_plain(value: str | None) -> str | None:
    """The other spelling: accents dropped, so "Muller" finds "Müller" and
    "cafe" finds "Café"."""
    if value is None:
        return None
    decomposed = unicodedata.normalize("NFKD", value.lower().replace("ß", "ss"))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


@event.listens_for(Engine, "connect")
def _register_sql_functions(dbapi_connection, _connection_record):
    # fold(text) in SQL — every engine, including the tests' own
    if hasattr(dbapi_connection, "create_function"):
        dbapi_connection.create_function("fold", 1, fold_text, deterministic=True)
        dbapi_connection.create_function("fold_plain", 1, fold_plain, deterministic=True)


engine: Engine = _build_engine()


def init_db() -> None:
    """Bring the database schema up to the latest Alembic migration.

    Safe to call on every startup: a brand-new database is created from
    scratch by the migration chain; an existing database is upgraded
    in-place with only the incremental changes, preserving all data.
    Tests bypass this and use SQLModel.metadata.create_all directly
    against throwaway databases, so this function only runs for the real
    application.
    """
    from app.db.migrate import run_migrations_to_head

    run_migrations_to_head()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with Session(engine) as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for use outside of FastAPI request handling (e.g. services, tests)."""
    with Session(engine) as session:
        yield session
