"""Central configuration for the finance backend.

Settings are resolved in this order (highest priority first):

1. environment variables prefixed with ``FINANCE_`` (e.g. ``FINANCE_PORT``)
2. ``finance.env`` in the repository root — written by the install
   scripts, so the user's choices (data directory, port, ...) survive
   re-installs and apply no matter which directory the app is started from
3. the defaults below

Financial data lives in the per-user application data directory (e.g.
``~/.local/share/finance-analyzer`` on Linux,
``%LOCALAPPDATA%\\finance-analyzer`` on Windows), NOT inside the source
checkout — so ``git clean``, deleting the checkout or re-cloning can never
destroy the database, and nothing sensitive can be committed by accident.
Databases created by older versions inside ``<repo>/data`` keep working
(see ``Settings._resolve_paths``); the install scripts offer to move them.
"""
from __future__ import annotations

from pathlib import Path

import platformdirs
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "finance-analyzer"
APP_VERSION = "0.8.0"

# backend/app/config.py -> repo root is two levels up
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = REPO_ROOT / "finance.env"

# Pre-0.2 layout: everything lived inside the checkout.
LEGACY_DATA_DIR = REPO_ROOT / "data"
LEGACY_IMPORTS_DIR = REPO_ROOT / "imports"
LEGACY_EXPORTS_DIR = REPO_ROOT / "exports"
LEGACY_BACKUPS_DIR = REPO_ROOT / "backups"

DATABASE_FILENAME = "finance.db"


def default_data_dir() -> Path:
    return Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))


def legacy_database_exists() -> bool:
    return (LEGACY_DATA_DIR / DATABASE_FILENAME).exists()


class Settings(BaseSettings):
    # utf-8-sig: finance.env is written as UTF-8 by the installers (paths may
    # contain umlauts); the Windows default code page would misread it, and
    # an editor-added BOM must not break the first line.
    model_config = SettingsConfigDict(
        env_prefix="FINANCE_", env_file=CONFIG_FILE, env_file_encoding="utf-8-sig", extra="ignore"
    )

    # All four directories are optional overrides; unset ones are derived
    # from data_dir in _resolve_paths, so after validation they are always
    # concrete paths.
    data_dir: Path | None = None
    imports_dir: Path | None = None
    exports_dir: Path | None = None
    backups_dir: Path | None = None

    database_filename: str = DATABASE_FILENAME

    # Bind to localhost only unless explicitly overridden — this app
    # handles sensitive financial data and has no user authentication, so
    # it must not be exposed to the network by default.
    host: str = "127.0.0.1"
    port: int = 8420
    # Extra Host-header values to accept, comma-separated. Only needed when
    # deliberately binding to something other than localhost.
    allowed_hosts: str = ""
    open_browser: bool = False

    max_upload_size_bytes: int = 50 * 1024 * 1024  # 50 MB per imported statement
    max_backup_upload_bytes: int = 2 * 1024 * 1024 * 1024  # 2 GB per uploaded backup ZIP
    max_backup_uncompressed_bytes: int = 8 * 1024 * 1024 * 1024  # zip-bomb guard
    allowed_upload_extensions: tuple[str, ...] = (".csv", ".xlsx", ".pdf")
    staging_max_age_hours: int = 24

    using_legacy_layout: bool = False

    @model_validator(mode="after")
    def _resolve_paths(self) -> Settings:
        if self.data_dir is None:
            if legacy_database_exists():
                # Keep existing pre-0.2 installs working exactly where their
                # data already is, until the user moves it (install script).
                self.data_dir = LEGACY_DATA_DIR
                self.imports_dir = self.imports_dir or LEGACY_IMPORTS_DIR
                self.exports_dir = self.exports_dir or LEGACY_EXPORTS_DIR
                self.backups_dir = self.backups_dir or LEGACY_BACKUPS_DIR
                self.using_legacy_layout = True
            else:
                self.data_dir = default_data_dir()
        self.data_dir = self.data_dir.expanduser()
        self.imports_dir = (self.imports_dir or self.data_dir / "imports").expanduser()
        self.exports_dir = (self.exports_dir or self.data_dir / "exports").expanduser()
        self.backups_dir = (self.backups_dir or self.data_dir / "backups").expanduser()
        return self

    @property
    def staging_dir(self) -> Path:
        return self.data_dir / ".staging"

    @property
    def database_path(self) -> Path:
        return self.data_dir / self.database_filename

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    @property
    def allowed_host_names(self) -> set[str]:
        names = {"127.0.0.1", "localhost", "::1"}
        names.update(h.strip().lower() for h in self.allowed_hosts.split(",") if h.strip())
        if self.host not in ("0.0.0.0", "::"):  # noqa: S104 — wildcard binds add no host name
            names.add(self.host.lower())
        return names

    def ensure_directories(self) -> None:
        for d in (self.data_dir, self.imports_dir, self.exports_dir, self.staging_dir, self.backups_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
