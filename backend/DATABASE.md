# Database & Migrations

## How schema changes work

This app uses [Alembic](https://alembic.sqlalchemy.org/) for schema migrations.
The database schema is never created or changed by deleting/recreating
the database file — every change goes through a migration, applied in
order, so existing financial data is always preserved.

**You don't need to run anything manually for normal use.** Every time
the backend starts (`run.sh` / `run.bat`, or `python -m app`), it
automatically brings the database up to the latest schema:

- **Brand-new install** (no `finance.db` yet): all tables are created
  from scratch by running the full migration chain.
- **Existing database**: only the migrations it hasn't seen yet are
  applied, in place. Nothing is deleted or recreated.

This happens in `app/db/session.py::init_db()`, called on app startup.

## Bridge for databases created before migrations existed

Early in this project's development, the database schema was created
directly from the Python models (`SQLModel.metadata.create_all`) rather
than through Alembic. Such a database has the app's tables but no
`alembic_version` table. On startup, `app/db/migrate.py` inspects its
schema, determines the newest migration whose changes are already present
(`_detect_unversioned_revision`), stamps the database with that revision
and then applies the remaining migrations normally.

(Earlier versions stamped such databases as "head" unconditionally, which
silently skipped migrations when the database was older than the newest
one.)

**When you add a migration, add a matching check to
`_detect_unversioned_revision`** (newest first), e.g. "column X exists in
table Y → revision Z".

You can see this happen in the startup log:
```
INFO  [alembic.runtime.migration] Running stamp_revision  -> <revision>
INFO  [alembic.runtime.migration] Running upgrade <revision> -> <next>, ...
```

## A copy before every upgrade

SQLite can't undo a schema change that stopped half-way (Alembic runs its
DDL outside a transaction there): after a full disk or a killed process the
database may hold part of a migration without its version stamp, and every
later start fails on it. So before the app upgrades its own database on
start-up, it copies it to the backups folder as
`pre-upgrade-<revision>-<time>.db` (`run_migrations_to_head` in
`app/db/migrate.py`; SQLite's backup API, checked with `integrity_check`).
The newest three such copies are kept. No copy is made for a new database
or one that is already up to date, and if the copy can't be made the
upgrade doesn't start.

To go back after a failed upgrade: stop the app, install its previous
version, and put the copy in place of `finance.db` (remove `finance.db-wal`
and `finance.db-shm` next to it, if present).

## Restoring backups from older versions

A restored backup is extracted to a temporary folder and migrated to the
current schema *before* it replaces the live database, so restoring a
backup made by an older version just works. A backup made by a *newer*
version (unknown revision) is rejected with a clear message.

## Manual migration commands

Useful when developing, or to inspect/control migrations directly.
Run from the `backend/` directory (they act on the database configured in
`finance.env` / `FINANCE_DATA_DIR`):

```bash
# Check the current migration state of your database
uv run alembic current            # or: .venv/bin/alembic current

# See the full migration history
alembic history

# Apply all pending migrations (same thing init_db() does automatically)
alembic upgrade head

# Verify the migration files exactly match the current models
# (fails if you changed a model without generating a migration for it)
alembic check
```

## Adding a new migration (for developers)

When you change a model in `app/db/models.py`:

```bash
cd backend
alembic revision --autogenerate -m "short description of the change"
```

Then **review the generated file** in `app/db/migrations/versions/` before
committing — autogenerate is a strong starting point, not a guarantee
(it won't detect every kind of change, e.g. some renames or data
migrations need to be written by hand). Run `alembic check` afterward to
confirm the migration file and your models now agree.

All migrations use SQLite "batch mode" (`render_as_batch=True` in
`env.py`), which is required for `ALTER TABLE` operations like adding a
column, since SQLite's native `ALTER TABLE` support is limited.

## Where the database lives

`finance.db` in the data folder — by default the per-user application data
folder (`~/.local/share/finance-analyzer` on Linux,
`~/Library/Application Support/finance-analyzer` on macOS,
`%LOCALAPPDATA%\finance-analyzer` on Windows), or whatever
`FINANCE_DATA_DIR` in `finance.env` says (see `app/config.py`).
Installations from before version 0.2 kept it in `data/finance.db` inside
the repository; that location keeps working until the installer moves it.

Back it up via Settings → Backup (a consistent snapshot plus all original
documents), or by copying the whole data folder while the app is not
running.
