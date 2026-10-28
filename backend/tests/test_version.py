"""The version is written in three places; a release must change all of them."""
from __future__ import annotations

import json
import tomllib

from app.config import APP_VERSION, REPO_ROOT


def test_backend_frontend_and_package_versions_agree():
    pyproject = tomllib.loads((REPO_ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == APP_VERSION == package["version"]
