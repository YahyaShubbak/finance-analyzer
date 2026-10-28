"""Alembic environment.

The database URL always comes from app.config.settings (single source of
truth — matches what the running application actually connects to), not
from a hardcoded value in alembic.ini. This means `alembic upgrade head`
targets the same database the app uses, wherever FINANCE_DATA_DIR points.
"""
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make `app` importable when alembic is invoked from the backend/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.config import settings  # noqa: E402
from app.db.models import SQLModel  # noqa: E402  (imports all models via app.db.models)

config = context.config

# Respect a URL the caller already configured (e.g. tests pointing at a
# throwaway database via Config.set_main_option before invoking
# command.upgrade); only fall back to the real app's database when the
# ini's placeholder default is still in place (plain `alembic <cmd>` CLI
# usage). Never silently redirect an explicit caller-supplied URL to the
# app's real database.
_configured_url = config.get_main_option("sqlalchemy.url")
if not _configured_url or _configured_url == "driver://user:pass@localhost/dbname":
    settings.ensure_directories()  # plain `alembic upgrade head` on a fresh install
    config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    # Migrations also run inside the app (start-up, restore): keep its own
    # loggers (uvicorn, "finance") working, or errors would vanish silently.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite needs batch mode for ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite needs batch mode for ALTER TABLE support
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
