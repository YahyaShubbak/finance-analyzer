"""SQLite engine + session management.

The database is the persistent source of truth. We enable WAL mode and
foreign key enforcement, and never drop/recreate the database on schema
change — migrations are handled via Alembic.
"""
from __future__ import annotations

import threading
import unicodedata
import weakref
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession
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


# ---------------------------------------------------------------------------
# Values worked out from all the data, kept until the data changes
# ---------------------------------------------------------------------------
# The chains among the payees, what each merchant is usually sorted as, the
# model that suggests categories: each is built by reading every booking.
# Built once per state of the data instead of once per request, they turn
# seconds of work per click into none. "State of the data" is counted in
# commits: any commit through a session makes every remembered value stale.
# What only depends on which bookings exist and on their payee texts (the
# chains) outlives commits that change neither — sorting a booking into a
# category, the most frequent change of all.

_generation = 0        # any committed change
_payee_generation = 0  # committed changes of which bookings exist, or of a booking's merchant / description
_remembered: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()  # engine -> {name: (generation, value)}
_UNCOMMITTED = "writes_since_commit"
_PAYEES_TOUCHED = "payee_writes_since_commit"


def note_data_changed() -> None:
    """The data changed without a session's commit telling (the database
    file was replaced by a restore): forget what was remembered."""
    global _generation, _payee_generation
    _generation += 1
    _payee_generation += 1


def _touches_payees(session) -> bool:
    from sqlalchemy import inspect as state_of

    from app.db.models import Transaction

    if any(isinstance(obj, Transaction) for obj in (*session.new, *session.deleted)):
        return True
    for obj in session.dirty:
        if isinstance(obj, Transaction):
            attributes = state_of(obj).attrs
            if attributes.merchant.history.has_changes() or attributes.normalized_description.history.has_changes():
                return True
    return False


@event.listens_for(OrmSession, "after_commit")
def _committed(session) -> None:
    global _generation, _payee_generation
    session.info.pop(_UNCOMMITTED, None)
    _generation += 1
    if session.info.pop(_PAYEES_TOUCHED, None):
        _payee_generation += 1


@event.listens_for(OrmSession, "after_flush")
def _flushed(session, _flush_context) -> None:
    # (still before the flush is cleared away: new / dirty / deleted and the attributes' history are intact)
    session.info[_UNCOMMITTED] = True
    if _touches_payees(session):
        session.info[_PAYEES_TOUCHED] = True


@event.listens_for(OrmSession, "do_orm_execute")
def _executing(state) -> None:
    # An INSERT, UPDATE or DELETE statement changes data without a flush of
    # objects — whatever it touches, so it counts for everything.
    if state.is_insert or state.is_update or state.is_delete:
        state.session.info[_UNCOMMITTED] = True
        state.session.info[_PAYEES_TOUCHED] = True


@event.listens_for(OrmSession, "after_soft_rollback")
def _rolled_back(session, _previous_transaction) -> None:
    session.info.pop(_UNCOMMITTED, None)
    session.info.pop(_PAYEES_TOUCHED, None)


def remembered[T](session: Session, name: str, build: Callable[[], T], *, payees_only: bool = False) -> T:
    """`build()`'s result for the committed data `session` reads — built once
    and shared (so never to be changed by a caller) until something is
    committed. A session holding changes of its own that are not committed
    yet sees other data than everyone else: it gets a fresh `build()`, and
    what it builds is not kept.

    `payees_only`: the value depends on nothing but which bookings exist and
    their merchant and description; it then stays through commits that
    change other things."""
    if session.info.get(_UNCOMMITTED) or session.new or session.dirty or session.deleted:
        return build()
    slot = _remembered.setdefault(session.get_bind(), {})
    generation = _payee_generation if payees_only else _generation
    hit = slot.get(name)
    if hit is not None and hit[0] == generation:
        return hit[1]
    value = build()
    slot[name] = (generation, value)
    return value


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
