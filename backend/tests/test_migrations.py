"""Verifies the Alembic migration chain upgrades an existing, populated
database in place without deleting or altering any financial data — the
exact scenario of an existing installation picking up a schema change.

This deliberately does NOT delete or recreate the database: it builds a
database on the pre-0002 baseline schema (migration 68438a4a1e4b only),
inserts realistic data through that older schema, then runs
`alembic upgrade head` and asserts every row is still there, unchanged,
plus that the new column exists and is safely nullable for existing rows.
"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
MIGRATIONS_DIR = BACKEND_DIR / "app" / "db" / "migrations"

BASELINE_REVISION = "68438a4a1e4b"  # "initial schema" — predates user_resolution_tags_json


def _alembic_config(db_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_migration_upgrades_existing_database_without_data_loss(tmp_path):
    db_path = tmp_path / "pre_migration.db"
    db_url = f"sqlite:///{db_path}"
    cfg = _alembic_config(db_url)

    # 1. Build the database on the OLD schema only (no user_resolution_tags_json column).
    command.upgrade(cfg, BASELINE_REVISION)

    engine = create_engine(db_url)
    columns_before = {c["name"] for c in inspect(engine).get_columns("reconciliations")}
    assert "user_resolution_tags_json" not in columns_before

    # 2. Insert realistic data directly against the old schema — an account,
    #    an import, raw+normalized transactions, a credit-card statement,
    #    and a reconciliation with real computed values and resolution notes.
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO accounts (id, name, account_type, currency, created_at, is_archived) "
            "VALUES (1, 'Checking', 'CHECKING', 'EUR', '2026-01-01T00:00:00', 0)"
        ))
        conn.execute(text(
            "INSERT INTO accounts (id, name, account_type, currency, created_at, is_archived) "
            "VALUES (2, 'VISA', 'CREDIT_CARD', 'EUR', '2026-01-01T00:00:00', 0)"
        ))
        conn.execute(text(
            "INSERT INTO imports (id, filename, stored_path, file_checksum, document_type, account_id, "
            "imported_at, status, detected_transaction_count) "
            "VALUES (1, 'march.pdf', 'imports/march.pdf', 'abc123', 'CREDIT_CARD_STATEMENT', 2, "
            "'2026-03-15T00:00:00', 'IMPORTED', 1)"
        ))
        conn.execute(text(
            "INSERT INTO raw_transactions (id, import_id, source_row_index, original_date_text, "
            "original_description, original_amount_text) "
            "VALUES (1, 1, 0, '02.03.2026', 'Amazon.de', '100.00')"
        ))
        conn.execute(text(
            "INSERT INTO transactions (id, raw_transaction_id, account_id, transaction_date, "
            "normalized_description, merchant, category, amount_minor, currency, transaction_type, "
            "duplicate_fingerprint, is_duplicate, is_transfer, created_at, updated_at) "
            "VALUES (1, 1, 2, '2026-03-02', 'Amazon.de', 'Amazon', 'Shopping', -10000, 'EUR', 'EXPENSE', "
            "'fp-1', 0, 0, '2026-03-02T00:00:00', '2026-03-02T00:00:00')"
        ))
        conn.execute(text(
            "INSERT INTO credit_card_statements (id, account_id, import_id, statement_period_start, "
            "statement_period_end, statement_total_minor, currency, created_at) "
            "VALUES (1, 2, 1, '2026-03-01', '2026-03-10', 10000, 'EUR', '2026-03-15T00:00:00')"
        ))
        conn.execute(text(
            "INSERT INTO reconciliations (id, statement_id, transaction_total_minor, statement_total_minor, "
            "status, resolved_by_user, resolution_notes, created_at, updated_at) "
            "VALUES (1, 1, 10000, 10000, 'RECONCILED', 1, 'Verified against paper statement', "
            "'2026-03-15T00:00:00', '2026-03-15T00:00:00')"
        ))

    engine.dispose()

    # 3. Upgrade in place — no deletion, no recreation of the database file.
    command.upgrade(cfg, "head")

    # 4. Every row must still be there, completely unchanged, and the new
    #    column must exist (nullable, so the pre-existing row gets NULL
    #    rather than losing data or failing the migration).
    engine = create_engine(db_url)
    with engine.connect() as conn:
        columns_after = {c["name"] for c in inspect(conn).get_columns("reconciliations")}
        assert "user_resolution_tags_json" in columns_after

        accounts = conn.execute(text("SELECT id, name, account_type FROM accounts ORDER BY id")).fetchall()
        assert [tuple(r) for r in accounts] == [(1, "Checking", "CHECKING"), (2, "VISA", "CREDIT_CARD")]

        imp = conn.execute(text("SELECT filename, file_checksum FROM imports WHERE id=1")).fetchone()
        assert tuple(imp) == ("march.pdf", "abc123")

        raw = conn.execute(text("SELECT original_description, original_amount_text FROM raw_transactions WHERE id=1")).fetchone()
        assert tuple(raw) == ("Amazon.de", "100.00")

        tx = conn.execute(text("SELECT merchant, category, amount_minor FROM transactions WHERE id=1")).fetchone()
        assert tuple(tx) == ("Amazon", "Shopping", -10000)

        stmt = conn.execute(text("SELECT statement_total_minor, currency FROM credit_card_statements WHERE id=1")).fetchone()
        assert tuple(stmt) == (10000, "EUR")

        rec = conn.execute(text(
            "SELECT transaction_total_minor, statement_total_minor, status, resolved_by_user, "
            "resolution_notes, user_resolution_tags_json FROM reconciliations WHERE id=1"
        )).fetchone()
        assert tuple(rec) == (10000, 10000, "RECONCILED", 1, "Verified against paper statement", None)

    engine.dispose()

    # 5. The migrated rows must also be readable through the ORM exactly
    #    as the app reads them (enum columns store member NAMES).
    from sqlmodel import Session, select

    from app.db.models import Account, AccountType, Reconciliation, ReconciliationStatus, Transaction
    engine = create_engine(db_url)
    with Session(engine) as session:
        assert {a.account_type for a in session.exec(select(Account)).all()} == {
            AccountType.CHECKING, AccountType.CREDIT_CARD,
        }
        assert session.exec(select(Reconciliation)).one().status == ReconciliationStatus.RECONCILED
        assert session.exec(select(Transaction)).one().settles_statement_id is None
    engine.dispose()


def test_fresh_database_created_entirely_through_migrations(tmp_path):
    db_path = tmp_path / "fresh.db"
    db_url = f"sqlite:///{db_path}"
    cfg = _alembic_config(db_url)

    command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()

    expected = {
        "accounts", "imports", "raw_transactions", "transactions", "user_corrections",
        "merchant_rules", "category_rules", "credit_card_statements", "reconciliations",
        "alembic_version",
    }
    assert expected.issubset(tables)


def test_migrations_match_current_models_with_no_drift(tmp_path):
    """Guards against forgetting to generate a migration for a future model
    change — if this fails, a model was edited without `alembic revision
    --autogenerate` being run."""
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    from app.db.models import SQLModel

    db_path = tmp_path / "drift_check.db"
    db_url = f"sqlite:///{db_path}"
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        diff = compare_metadata(ctx, SQLModel.metadata)
    engine.dispose()

    assert diff == [], f"Model/migration drift detected: {diff}"


def test_running_migrations_keeps_the_apps_loggers_working(tmp_path):
    """Migrations run inside the app (start-up, restore); Alembic's logging
    set-up must not switch off uvicorn's and the app's loggers, or errors
    after start-up would leave no trace."""
    import logging

    loggers = [logging.getLogger(name) for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "finance")]
    command.upgrade(_alembic_config(f"sqlite:///{tmp_path / 'log.db'}"), "head")
    assert [lg.disabled for lg in loggers] == [False] * 4


# ---------------------------------------------------------------------------
# The app's own database is copied before its schema changes
# ---------------------------------------------------------------------------

def _own_database(tmp_path, monkeypatch):
    """Point the app's settings at an empty data folder; returns the database path."""
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "imports_dir", tmp_path / "data" / "imports")
    monkeypatch.setattr(settings, "exports_dir", tmp_path / "data" / "exports")
    monkeypatch.setattr(settings, "backups_dir", tmp_path / "backups")
    settings.ensure_directories()
    return settings.database_path


def _old_database_with_an_account(db_path):
    command.upgrade(_alembic_config(f"sqlite:///{db_path}"), BASELINE_REVISION)
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO accounts (id, name, account_type, currency, created_at, is_archived) "
            "VALUES (1, 'Checking', 'CHECKING', 'EUR', '2026-01-01T00:00:00', 0)"
        ))
    engine.dispose()


def _revision(db_path) -> str:
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    finally:
        conn.close()


def _copies(tmp_path):
    return sorted((tmp_path / "backups").glob("pre-upgrade-*"))


def test_database_is_copied_before_its_schema_is_upgraded(tmp_path, monkeypatch):
    import sqlite3

    from app.db.migrate import known_revisions, run_migrations_to_head

    db_path = _own_database(tmp_path, monkeypatch)
    _old_database_with_an_account(db_path)

    run_migrations_to_head()

    [copy] = _copies(tmp_path)
    assert copy.name.startswith(f"pre-upgrade-{BASELINE_REVISION}-") and copy.suffix == ".db"
    # the copy is the database as it was: old schema, with its data
    assert _revision(copy) == BASELINE_REVISION
    conn = sqlite3.connect(copy)
    try:
        assert conn.execute("SELECT name FROM accounts").fetchall() == [("Checking",)]
        assert "iban" not in {row[1] for row in conn.execute("PRAGMA table_info(accounts)")}
    finally:
        conn.close()
    # ... and the app's database is upgraded, with its data
    assert _revision(db_path) != BASELINE_REVISION and _revision(db_path) in known_revisions()
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT name, iban FROM accounts").fetchall() == [("Checking", None)]
    finally:
        conn.close()


def test_no_copy_for_a_new_database_or_one_that_is_up_to_date(tmp_path, monkeypatch):
    from app.db.migrate import run_migrations_to_head

    _own_database(tmp_path, monkeypatch)
    run_migrations_to_head()  # a new installation
    run_migrations_to_head()  # every later start
    assert _copies(tmp_path) == []


def test_no_copy_for_a_current_database_that_only_lacks_its_version_stamp(tmp_path, monkeypatch):
    """A database built from the current models (as the tests' own are) is
    recognized as up to date: stamped, nothing to upgrade, nothing to copy."""
    from sqlmodel import SQLModel

    from app.db.migrate import _schema_revision, known_revisions, run_migrations_to_head

    db_path = _own_database(tmp_path, monkeypatch)
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    engine.dispose()
    revision, unversioned = _schema_revision(db_path)
    assert unversioned and revision in known_revisions()

    run_migrations_to_head()

    assert _copies(tmp_path) == []
    assert _revision(db_path) == revision


def test_failed_upgrade_keeps_the_copy_and_says_where_it_is(tmp_path, monkeypatch):
    import logging

    import pytest

    from app.db import migrate

    db_path = _own_database(tmp_path, monkeypatch)
    _old_database_with_an_account(db_path)

    def broken_upgrade(_cfg, _revision):
        raise RuntimeError("disk full")

    # (a handler of its own: Alembic's logging set-up replaces the root logger's, pytest's included)
    logged: list[str] = []
    handler = logging.Handler(level=logging.ERROR)
    handler.emit = lambda record: logged.append(record.getMessage())
    finance_logger = logging.getLogger("finance")
    finance_logger.addHandler(handler)
    monkeypatch.setattr(migrate.command, "upgrade", broken_upgrade)
    try:
        with pytest.raises(RuntimeError, match="disk full"):
            migrate.run_migrations_to_head()
    finally:
        finance_logger.removeHandler(handler)

    [copy] = _copies(tmp_path)
    assert _revision(copy) == BASELINE_REVISION
    assert any(str(copy) in message for message in logged)


def test_database_is_not_upgraded_when_it_cannot_be_copied_first(tmp_path, monkeypatch):
    import pytest

    from app.config import settings
    from app.db.migrate import run_migrations_to_head

    db_path = _own_database(tmp_path, monkeypatch)
    _old_database_with_an_account(db_path)
    blocked = tmp_path / "not-a-folder"
    blocked.write_text("a file where the backups folder should be")
    monkeypatch.setattr(settings, "backups_dir", blocked)
    monkeypatch.setattr(type(settings), "ensure_directories", lambda _self: None)

    with pytest.raises(RuntimeError, match="Nothing was changed"):
        run_migrations_to_head()

    assert _revision(db_path) == BASELINE_REVISION


def test_only_the_newest_copies_from_before_upgrades_are_kept(tmp_path, monkeypatch):
    import os

    from app.db.migrate import PRE_UPGRADE_COPIES_KEPT, run_migrations_to_head

    db_path = _own_database(tmp_path, monkeypatch)
    _old_database_with_an_account(db_path)
    backups = tmp_path / "backups"
    for age in range(1, 6):
        old = backups / f"pre-upgrade-0000-2020010{age}-000000.db"
        old.write_bytes(b"old copy")
        os.utime(old, (1_577_836_800 + age, 1_577_836_800 + age))
    (backups / "finance-backup-kept.zip").write_bytes(b"a backup the user made")

    run_migrations_to_head()

    names = [path.name for path in _copies(tmp_path)]
    assert len(names) == PRE_UPGRADE_COPIES_KEPT
    assert any(name.startswith(f"pre-upgrade-{BASELINE_REVISION}-") for name in names)  # the new one
    assert "pre-upgrade-0000-20200105-000000.db" in names and "pre-upgrade-0000-20200101-000000.db" not in names
    assert (backups / "finance-backup-kept.zip").exists()


# ---------------------------------------------------------------------------
# An import's id is never given to a later import
# ---------------------------------------------------------------------------

_NEW_IMPORT = (
    "INSERT INTO imports (filename, stored_path, file_checksum, document_type, imported_at, status, "
    "detected_transaction_count) VALUES (:name, :name, :name, 'BANK_STATEMENT', '2026-03-15T00:00:00', 'IMPORTED', 0)"
)


def _ids_after_removing_the_newest_import(db_url: str) -> tuple[int, int]:
    """(id of the removed newest import, id of the import made after that)."""
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text(_NEW_IMPORT), {"name": "january.csv"})
        removed = conn.execute(text(_NEW_IMPORT), {"name": "february.csv"}).lastrowid
        conn.execute(text("DELETE FROM imports WHERE id = :id"), {"id": removed})
        following = conn.execute(text(_NEW_IMPORT), {"name": "march.csv"}).lastrowid
    engine.dispose()
    return removed, following


def test_import_id_is_not_reused_in_a_database_built_by_migrations(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'ids.db'}"
    command.upgrade(_alembic_config(db_url), "head")
    removed, following = _ids_after_removing_the_newest_import(db_url)
    assert following > removed


def test_import_id_is_not_reused_in_a_database_built_from_the_models(tmp_path):
    from sqlmodel import SQLModel

    db_url = f"sqlite:///{tmp_path / 'ids.db'}"
    engine = create_engine(db_url)
    SQLModel.metadata.create_all(engine)
    engine.dispose()
    removed, following = _ids_after_removing_the_newest_import(db_url)
    assert following > removed


def test_existing_imports_keep_their_ids_and_rows_when_ids_stop_being_reused(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'ids.db'}"
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, "b7d3e9a41c52")  # the revision before
    engine = create_engine(db_url)
    with engine.begin() as conn:
        for import_id, name in ((3, "january.csv"), (7, "february.csv")):
            conn.execute(text(
                "INSERT INTO imports (id, filename, stored_path, file_checksum, document_type, imported_at, "
                "status, detected_transaction_count, source_key) VALUES (:id, :name, :name, :name, "
                "'BANK_STATEMENT', '2026-03-15T00:00:00', 'IMPORTED', 1, 'kind')"
            ), {"id": import_id, "name": name})
        conn.execute(text("INSERT INTO raw_transactions (id, import_id, source_row_index) VALUES (1, 7, 0)"))
        before = conn.execute(text("SELECT * FROM imports ORDER BY id")).fetchall()
        indexes_before = {i["name"] for i in inspect(conn).get_indexes("imports")}
    engine.dispose()

    command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    with engine.begin() as conn:
        assert conn.execute(text("SELECT * FROM imports ORDER BY id")).fetchall() == before
        assert {i["name"] for i in inspect(conn).get_indexes("imports")} == indexes_before
        conn.execute(text("PRAGMA foreign_keys=ON"))
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []
        assert conn.execute(text("SELECT import_id FROM raw_transactions")).scalar() == 7
        conn.execute(text("DELETE FROM raw_transactions"))
        conn.execute(text("DELETE FROM imports WHERE id = 7"))
        assert conn.execute(text(_NEW_IMPORT), {"name": "march.csv"}).lastrowid == 8
    engine.dispose()
