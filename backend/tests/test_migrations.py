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
