from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Must happen before anything imports app.config: tests must never read or
# create the real per-user data directory, nor pick up a local finance.env.
# Environment variables take precedence over that file, so every setting it
# may hold is set here — its folders, port or host never reach a test.
_test_data_dir = Path(tempfile.mkdtemp(prefix="finance-tests-"))
os.environ.update({
    "FINANCE_DATA_DIR": str(_test_data_dir),
    "FINANCE_IMPORTS_DIR": str(_test_data_dir / "imports"),
    "FINANCE_EXPORTS_DIR": str(_test_data_dir / "exports"),
    "FINANCE_BACKUPS_DIR": str(_test_data_dir / "backups"),
    "FINANCE_HOST": "127.0.0.1",
    "FINANCE_PORT": "8420",
    "FINANCE_ALLOWED_HOSTS": "",
    "FINANCE_OPEN_BROWSER": "false",
})

# imported only now, after the environment above (E402 on purpose)
import pytest  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

from app.db.models import Account, AccountType  # noqa: E402


def enforce_foreign_keys(engine):
    """As the app's own engine does (app.db.session): a test must not pass
    with a reference the app's database would refuse."""
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


@pytest.fixture()
def engine(tmp_path):
    db_path = tmp_path / "test_finance.db"
    eng = enforce_foreign_keys(create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False}))
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture()
def checking_account(session) -> Account:
    acc = Account(name="Checking Account", account_type=AccountType.CHECKING, currency="EUR")
    session.add(acc)
    session.commit()
    session.refresh(acc)
    return acc


@pytest.fixture()
def savings_account(session) -> Account:
    acc = Account(name="Savings Account", account_type=AccountType.SAVINGS, currency="EUR")
    session.add(acc)
    session.commit()
    session.refresh(acc)
    return acc


@pytest.fixture()
def credit_card_account(session) -> Account:
    acc = Account(name="VISA Credit Card", account_type=AccountType.CREDIT_CARD, currency="EUR")
    session.add(acc)
    session.commit()
    session.refresh(acc)
    return acc


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """FastAPI TestClient wired to an isolated on-disk test DB, shared
    across all API-route test modules."""
    from fastapi.testclient import TestClient

    import app.db.session as db_session
    from app.config import settings
    from app.main import app
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "imports_dir", tmp_path / "imports")
    monkeypatch.setattr(settings, "exports_dir", tmp_path / "exports")
    monkeypatch.setattr(settings, "backups_dir", tmp_path / "backups")
    settings.ensure_directories()

    # Patch the actual module-level engine singleton (rather than
    # overriding the get_session dependency with a separate engine
    # object) so that code which manipulates the engine directly by
    # importing it — e.g. the backup service disposing pooled connections
    # before replacing the database file — affects the same engine these
    # requests are really using. A dependency-override-only approach would
    # leave a second, undisposed engine holding a stale connection to the
    # just-replaced file.
    db_path = settings.database_path
    test_engine = enforce_foreign_keys(
        create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False}))
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(db_session, "engine", test_engine)

    # Same host and client header as the real frontend — see app.security.
    with TestClient(app, base_url="http://127.0.0.1:8420", headers={"X-Finance-Client": "1"}) as c:
        yield c
