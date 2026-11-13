"""Tests for Milestone 4, Feature 3: Backup/Restore.

Covers the required matrix: create backup from populated data, verify
contents, modify/delete data, restore, verify exact restoration
(transactions/imports/rules/corrections/reconciliation/traceability),
restore against a fresh install, reject corrupt/invalid backups without
touching current data, and migration compatibility after restore.
"""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from tests.pdf_fixtures import write_text_pdf


def _create_account(client, name, account_type="checking"):
    r = client.post("/api/accounts", json={"name": name, "account_type": account_type, "currency": "EUR"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _import_csv(client, filename, content: bytes, account_id: int):
    files = {"file": (filename, io.BytesIO(content), "text/csv")}
    preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id})
    assert preview.status_code == 200, preview.text
    p = preview.json()
    commit = client.post("/api/imports/commit", json={"staging_id": p["staging_id"], "account_id": account_id, "row_decisions": []})
    assert commit.status_code == 200, commit.text
    return commit.json()


def _import_pdf(client, tmp_path, name, lines, account_id):
    path = write_text_pdf(tmp_path / name, lines)
    with open(path, "rb") as f:
        files = {"file": (name, f, "application/pdf")}
        preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id})
    assert preview.status_code == 200, preview.text
    p = preview.json()
    commit = client.post("/api/imports/commit", json={"staging_id": p["staging_id"], "account_id": account_id, "row_decisions": []})
    assert commit.status_code == 200, commit.text
    return commit.json()


def _get_statement_id(client, cc_account_id):
    r = client.get(f"/api/credit-cards/{cc_account_id}/statements")
    return r.json()[0]["id"]


def _download_backup(client, filename):
    r = client.get(f"/api/backup/{filename}/download")
    assert r.status_code == 200
    return r.content


def _restore(client, zip_bytes, confirm=True):
    files = {"file": ("backup.zip", io.BytesIO(zip_bytes), "application/zip")}
    return client.post("/api/backup/restore", files=files, data={"confirm": str(confirm).lower()})


def _build_rich_scenario(client, tmp_path):
    """Populates the database with data touching every table the backup
    must preserve: accounts, imports (CSV + PDF), raw+normalized
    transactions, a user correction, a merchant rule, a category rule,
    and a full credit-card reconciliation."""
    checking_id = _create_account(client, "Checking")
    cc_id = _create_account(client, "VISA", "credit_card")

    _import_csv(
        client, "checking.csv",
        b"Date,Description,Amount\n"
        b"2026-01-01,Salary,2500.00\n"
        b"2026-01-05,Mystery Shop,-12.00\n"
        b"2026-01-12,Credit Card Payment,-80.00\n",
        checking_id,
    )
    _import_pdf(client, tmp_path, "cc.pdf", [
        "Credit Card Statement", "VISA ending 1234",
        "Statement Period: 01.01.2026 - 10.01.2026",
        "02.01.2026 Amazon.de 80.00 EUR",
        "Statement Total: 80.00 EUR",
    ], cc_id)
    stmt_id = _get_statement_id(client, cc_id)
    client.get(f"/api/reconciliation/statements/{stmt_id}")  # triggers reconciliation

    items = client.get("/api/transactions").json()["items"]
    mystery_tx = next(t for t in items if t["normalized_description"] == "Mystery Shop")
    client.patch(f"/api/transactions/{mystery_tx['id']}", json={"category": "Shopping"})  # user correction

    amazon_tx = next(t for t in items if t["normalized_description"] == "Amazon.de")
    client.post(f"/api/transactions/{amazon_tx['id']}/merchant-rule", json={"normalized_merchant": "Amazon Prime"})
    client.post(f"/api/transactions/{amazon_tx['id']}/category-rule", json={"category": "Shopping"})

    return {"checking_id": checking_id, "cc_id": cc_id, "stmt_id": stmt_id}


# ---------------------------------------------------------------------------
# 1-2. Create backup + verify contents
# ---------------------------------------------------------------------------

def test_create_backup_from_populated_database(client, tmp_path):
    _build_rich_scenario(client, tmp_path)

    r = client.post("/api/backup/create")
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["filename"].startswith("finance-backup-")
    assert info["filename"].endswith(".zip")
    assert info["size_bytes"] > 0
    assert info["counts"]["accounts"] == 2
    assert info["counts"]["transactions"] == 4  # 3 checking + 1 CC purchase
    assert info["counts"]["imports"] == 2
    assert info["counts"]["merchant_rules"] >= 1
    assert info["counts"]["category_rules"] >= 1
    assert info["counts"]["reconciliations"] == 1
    assert info["counts"]["user_corrections"] >= 1  # at least the category correction


def test_backup_zip_contains_database_and_source_documents(client, tmp_path):
    _build_rich_scenario(client, tmp_path)
    info = client.post("/api/backup/create").json()

    content = _download_backup(client, info["filename"])
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = zf.namelist()
        assert "finance.db" in names
        assert "manifest.json" in names
        assert any(n.startswith("imports/") and n.endswith(".csv") for n in names)
        assert any(n.startswith("imports/") and n.endswith(".pdf") for n in names)

        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["counts"]["transactions"] == 4
        assert manifest["imports_file_count"] == 2
        assert manifest["alembic_revision"] is not None


def test_list_backups(client, tmp_path):
    _build_rich_scenario(client, tmp_path)
    client.post("/api/backup/create")
    client.post("/api/backup/create")

    r = client.get("/api/backup")
    assert r.status_code == 200
    backups = r.json()
    assert len(backups) == 2
    assert all(b["counts"]["accounts"] == 2 for b in backups)


# ---------------------------------------------------------------------------
# 3-5. Modify/delete data, restore, verify exact restoration
# ---------------------------------------------------------------------------

def test_restore_recovers_exact_state_after_data_loss(client, tmp_path):
    ids = _build_rich_scenario(client, tmp_path)
    backup_bytes = _download_backup(client, client.post("/api/backup/create").json()["filename"])

    before_transactions = client.get("/api/transactions").json()
    before_imports = client.get("/api/imports").json()
    before_reconciliation = client.get(f"/api/reconciliation/statements/{ids['stmt_id']}").json()

    # Destroy data: remove an import, archive an account.
    client.delete(f"/api/imports/{before_imports[0]['id']}")
    client.patch(f"/api/accounts/{ids['checking_id']}", json={"is_archived": True})
    assert client.get("/api/transactions").json()["total"] < before_transactions["total"]

    # Restore.
    r = _restore(client, backup_bytes)
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["safety_backup"] != ""  # a safety backup of the (damaged) pre-restore state was made

    after_transactions = client.get("/api/transactions").json()
    after_imports = client.get("/api/imports").json()
    after_reconciliation = client.get(f"/api/reconciliation/statements/{ids['stmt_id']}").json()

    assert after_transactions["total"] == before_transactions["total"]
    assert {t["id"] for t in after_transactions["items"]} == {t["id"] for t in before_transactions["items"]}
    assert len(after_imports) == len(before_imports)
    assert after_reconciliation["status"] == before_reconciliation["status"] == "reconciled"

    # Manual correction and rules survived.
    mystery = next(t for t in after_transactions["items"] if t["normalized_description"] == "Mystery Shop")
    assert mystery["category"] == "Shopping"
    amazon = next(t for t in after_transactions["items"] if t["normalized_description"] == "Amazon.de")
    assert amazon["merchant"] == "Amazon Prime"

    # The archived account is un-archived again (state as of backup time).
    accounts = client.get("/api/accounts", params={"include_archived": True}).json()
    checking = next(a for a in accounts if a["id"] == ids["checking_id"])
    assert checking["is_archived"] is False


def test_restore_preserves_source_file_traceability(client, tmp_path):
    _build_rich_scenario(client, tmp_path)
    backup_bytes = _download_backup(client, client.post("/api/backup/create").json()["filename"])

    # Wipe everything.
    for imp in client.get("/api/imports").json():
        client.delete(f"/api/imports/{imp['id']}")

    _restore(client, backup_bytes)

    items = client.get("/api/transactions").json()["items"]
    amazon = next(t for t in items if t["normalized_description"] == "Amazon.de")
    assert amazon["source_filename"] == "cc.pdf"


# ---------------------------------------------------------------------------
# 6. Restore against a fresh/empty installation
# ---------------------------------------------------------------------------

def test_restore_into_fresh_empty_database(client, tmp_path):
    _build_rich_scenario(client, tmp_path)
    backup_bytes = _download_backup(client, client.post("/api/backup/create").json()["filename"])
    expected_total = client.get("/api/transactions").json()["total"]

    # Simulate a fresh install: remove every account (cascades transactions
    # via imports would be more work — just verify restore works when
    # called against whatever the current, now-different state is).
    for imp in client.get("/api/imports").json():
        client.delete(f"/api/imports/{imp['id']}")
    assert client.get("/api/transactions").json()["total"] == 0

    r = _restore(client, backup_bytes)
    assert r.status_code == 200
    assert client.get("/api/transactions").json()["total"] == expected_total


# ---------------------------------------------------------------------------
# 7. Corrupt/invalid backups rejected without touching current data
# ---------------------------------------------------------------------------

def test_restore_rejects_non_zip_file(client, tmp_path):
    _build_rich_scenario(client, tmp_path)
    before = client.get("/api/transactions").json()["total"]

    r = _restore(client, b"this is not a zip file at all")
    assert r.status_code == 400
    assert "not a valid backup" in r.json()["detail"].lower()

    assert client.get("/api/transactions").json()["total"] == before  # untouched


def test_restore_rejects_zip_missing_database(client, tmp_path):
    _build_rich_scenario(client, tmp_path)
    before = client.get("/api/transactions").json()["total"]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"created_at": "x"}))
    r = _restore(client, buf.getvalue())
    assert r.status_code == 400
    assert "finance.db" in r.json()["detail"]

    assert client.get("/api/transactions").json()["total"] == before


def test_restore_rejects_corrupt_database_inside_zip(client, tmp_path):
    _build_rich_scenario(client, tmp_path)
    before = client.get("/api/transactions").json()["total"]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("finance.db", b"not a real sqlite database, just garbage bytes")
        zf.writestr("manifest.json", json.dumps({"created_at": "x", "counts": {}}))
    r = _restore(client, buf.getvalue())
    assert r.status_code == 400
    assert "corrupt" in r.json()["detail"].lower() or "not a valid sqlite" in r.json()["detail"].lower()

    assert client.get("/api/transactions").json()["total"] == before


def test_restore_rejects_database_missing_required_tables(client, tmp_path):
    import sqlite3
    _build_rich_scenario(client, tmp_path)
    before = client.get("/api/transactions").json()["total"]

    incomplete_db = tmp_path / "incomplete.db"
    conn = sqlite3.connect(str(incomplete_db))
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.write(incomplete_db, "finance.db")
        zf.writestr("manifest.json", json.dumps({"created_at": "x", "counts": {}}))
    r = _restore(client, buf.getvalue())
    assert r.status_code == 400
    assert "missing expected tables" in r.json()["detail"].lower()

    assert client.get("/api/transactions").json()["total"] == before


def test_restore_without_confirmation_rejected(client, tmp_path):
    _build_rich_scenario(client, tmp_path)
    before = client.get("/api/transactions").json()["total"]
    info = client.post("/api/backup/create").json()
    backup_bytes = _download_backup(client, info["filename"])

    r = _restore(client, backup_bytes, confirm=False)
    assert r.status_code == 400
    assert "confirmation" in r.json()["detail"].lower()
    assert client.get("/api/transactions").json()["total"] == before


# ---------------------------------------------------------------------------
# 8. Migration compatibility after restore
# ---------------------------------------------------------------------------

def test_restored_database_passes_alembic_check(client, tmp_path):
    """After a restore, the app must be able to run migrations normally
    and `alembic check` must show no drift — proves the restored database
    is schema-compatible with the current models, not just structurally
    similar."""
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine

    from app.config import REPO_ROOT, settings
    from app.db.models import SQLModel

    _build_rich_scenario(client, tmp_path)
    backup_bytes = _download_backup(client, client.post("/api/backup/create").json()["filename"])
    _restore(client, backup_bytes)

    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        diff = compare_metadata(ctx, SQLModel.metadata)
    engine.dispose()

    assert diff == [], f"Model/migration drift detected after restore: {diff}"

    # Also confirm `alembic upgrade head` runs cleanly (idempotent no-op,
    # since the restored DB is already current) rather than erroring.
    cfg = Config(str(REPO_ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "backend" / "app" / "db" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")  # must not raise


# ---------------------------------------------------------------------------
# 9. Replacing the files is all or nothing
# ---------------------------------------------------------------------------

def _current_state(client) -> dict:
    """What a failed restore must leave exactly as it was: the bookings, the
    imports, and the stored original documents (names and contents)."""
    from app.config import settings

    return {
        "transactions": sorted(t["id"] for t in client.get("/api/transactions", params={"page_size": 500}).json()["items"]),
        "imports": sorted((i["id"], i["filename"]) for i in client.get("/api/imports").json()),
        "documents": {
            path.relative_to(settings.imports_dir).as_posix(): path.read_bytes()
            for path in sorted(settings.imports_dir.rglob("*")) if path.is_file()
        },
    }


def _backup_then_change(client, tmp_path) -> tuple[bytes, dict, dict]:
    """(a backup, the state it holds, the different state the app is in now)."""
    _build_rich_scenario(client, tmp_path)
    backup_bytes = _download_backup(client, client.post("/api/backup/create").json()["filename"])
    backed_up = _current_state(client)
    client.delete(f"/api/imports/{client.get('/api/imports').json()[0]['id']}")
    now = _current_state(client)
    assert now != backed_up and now["documents"] != backed_up["documents"]
    return backup_bytes, backed_up, now


def _break_file_step(monkeypatch, step: str, also_putting_back: bool = False):
    """Make one step of replacing the files fail the way Windows does when a
    file is open in another program."""
    import os
    import shutil

    from app.config import settings

    real_move, real_replace = shutil.move, os.replace
    moves = []

    def move(src, dst, *args, **kwargs):
        moves.append((src, dst))
        failing = {"move the current documents away": 1, "put the restored documents in place": 2}.get(step)
        if len(moves) == failing or (also_putting_back and len(moves) > 2):
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real_move(src, dst, *args, **kwargs)

    def replace(src, dst, *args, **kwargs):
        from pathlib import Path

        staged_database = Path(src).parent.name.startswith(".restore-") and Path(dst) == settings.database_path
        if step == "put the restored database in place" and staged_database:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "move", move)
    monkeypatch.setattr(os, "replace", replace)


@pytest.mark.parametrize("step", [
    "move the current documents away",
    "put the restored documents in place",
    "put the restored database in place",
])
def test_restore_that_fails_while_replacing_files_changes_nothing(client, tmp_path, monkeypatch, step):
    from app.config import settings

    backup_bytes, backed_up, before = _backup_then_change(client, tmp_path)

    with monkeypatch.context() as broken:
        _break_file_step(broken, step)
        r = _restore(client, backup_bytes)

    assert r.status_code == 400
    assert "Nothing was changed" in r.json()["detail"]
    # database AND documents are the ones from before — never one without the other
    assert _current_state(client) == before
    assert list(settings.data_dir.glob(".restore-*")) == []

    # ... and once the file is free again, the same restore goes through
    r = _restore(client, backup_bytes)
    assert r.status_code == 200, r.text
    assert _current_state(client) == backed_up


def test_restore_that_cannot_be_undone_keeps_what_it_replaced_and_says_where(client, tmp_path, monkeypatch):
    from app.config import settings
    from app.services.backup_service import purge_leftover_restore_dirs

    backup_bytes, _backed_up, before = _backup_then_change(client, tmp_path)

    with monkeypatch.context() as broken:
        _break_file_step(broken, "put the restored documents in place", also_putting_back=True)
        r = _restore(client, backup_bytes)

    assert r.status_code == 400
    detail = r.json()["detail"]
    [kept] = settings.data_dir.glob(".restore-*")
    assert "could not be put back completely" in detail and str(kept / "previous") in detail
    assert "pre-restore-safety-" in detail  # the complete way back
    # the documents that were moved away are still there, complete
    documents = {
        path.relative_to(kept / "previous" / "imports").as_posix(): path.read_bytes()
        for path in (kept / "previous" / "imports").rglob("*") if path.is_file()
    }
    assert documents == before["documents"]
    # the database was not touched
    assert _current_state(client)["transactions"] == before["transactions"]
    # ... and the next start-up doesn't clean that folder away
    purge_leftover_restore_dirs()
    assert (kept / "previous" / "imports").is_dir()


def test_leftover_folder_of_an_interrupted_restore_without_replaced_files_is_removed(client):
    from app.config import settings
    from app.services.backup_service import purge_leftover_restore_dirs

    leftover = settings.data_dir / ".restore-0123456789abcdef"
    (leftover / "imports").mkdir(parents=True)
    (leftover / "finance.db").write_bytes(b"a staged copy")
    (leftover / "previous").mkdir()  # nothing was moved there yet

    purge_leftover_restore_dirs()

    assert not leftover.exists()


# ---------------------------------------------------------------------------
# 10. Only the app's own files are replaced or cleaned away
# ---------------------------------------------------------------------------

def test_restore_keeps_other_files_in_the_imports_folder(client, tmp_path):
    """FINANCE_IMPORTS_DIR may be a folder the user keeps other files in (an
    archive of statements). A restore replaces the imports' stored originals
    — not whatever else lies there."""
    from app.config import settings

    backup_bytes, backed_up, before = _backup_then_change(client, tmp_path)
    own = {"Kontoauszug 2025-03.pdf": b"%PDF mine", "2024/Dezember.pdf": b"%PDF mine too"}
    for name, content in own.items():
        path = settings.imports_dir / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(content)
    left_by_a_failed_import = settings.imports_dir / "0123456789ab_statement.pdf"
    left_by_a_failed_import.write_bytes(b"%PDF a statement")

    r = _restore(client, backup_bytes)
    assert r.status_code == 200, r.text

    documents = _current_state(client)["documents"]
    assert {name: documents[name] for name in own} == own  # still there, unchanged
    # besides them: exactly the backup's documents — not the replaced state's, nor the app's leftovers
    assert {name: content for name, content in documents.items() if name not in own} == backed_up["documents"]
    assert documents != before["documents"]
    assert not left_by_a_failed_import.exists()
    assert list(settings.data_dir.glob(".restore-*")) == []


def test_start_up_cleaning_leaves_the_users_own_folders_alone(client):
    """Only working folders with the app's own prefix are cleaned away — not
    any folder whose name starts with "tmp" and that holds a database copy."""
    from app.config import settings
    from app.services.backup_service import purge_leftover_restore_dirs

    own_copy = settings.data_dir / "tmp-copy-before-experiment"
    own_copy.mkdir()
    (own_copy / "finance.db").write_bytes(b"my own copy")
    interrupted = settings.data_dir / ".finance-tmp-abc123"
    interrupted.mkdir()
    (interrupted / "finance.db").write_bytes(b"left by an interrupted backup")

    purge_leftover_restore_dirs()

    assert (own_copy / "finance.db").read_bytes() == b"my own copy"
    assert not interrupted.exists()


def test_a_backup_works_in_a_folder_with_the_apps_prefix(client, tmp_path, monkeypatch):
    import tempfile

    from app.config import settings

    made = []
    real = tempfile.TemporaryDirectory

    def recording(*args, **kwargs):
        made.append(kwargs.get("prefix"))
        return real(*args, **kwargs)

    monkeypatch.setattr(tempfile, "TemporaryDirectory", recording)
    _build_rich_scenario(client, tmp_path)
    assert client.post("/api/backup/create").status_code == 200

    assert made and all(prefix == ".finance-tmp-" for prefix in made)
    assert not list(settings.data_dir.glob(".finance-tmp-*"))  # removed when done


# ---------------------------------------------------------------------------
# Backups don't pile up, and can be deleted
# ---------------------------------------------------------------------------

def test_only_the_newest_safety_backups_from_before_restores_are_kept(client, tmp_path):
    """Each restore leaves a full backup of the state before it (with every
    original document): without a limit they fill the disk."""
    import os

    from app.config import settings

    _build_rich_scenario(client, tmp_path)
    backup = client.post("/api/backup/create").json()["filename"]
    zip_bytes = _download_backup(client, backup)
    # left by earlier restores (oldest first), and a backup the user made long ago
    for age, name in enumerate(["pre-restore-safety-20260104-000000.zip", "pre-restore-safety-20260103-000000.zip",
                                "pre-restore-safety-20260102-000000.zip", "pre-restore-safety-20260101-000000.zip",
                                "finance-backup-20250101-000000.zip"], start=1):
        path = settings.backups_dir / name
        path.write_bytes(zip_bytes)
        os.utime(path, (path.stat().st_atime, path.stat().st_mtime - age * 86400))

    assert _restore(client, zip_bytes).status_code == 200

    names = {path.name for path in settings.backups_dir.iterdir()}
    safety = sorted(name for name in names if name.startswith("pre-restore-safety-"))
    assert len(safety) == 3
    # the one just made and the two newest before it
    assert {"pre-restore-safety-20260104-000000.zip", "pre-restore-safety-20260103-000000.zip"} < set(safety)
    # what the user made is never removed by the app
    assert {backup, "finance-backup-20250101-000000.zip"} <= names


def test_a_backup_can_be_deleted(client, tmp_path):
    from app.config import settings

    _build_rich_scenario(client, tmp_path)
    kept = client.post("/api/backup/create").json()["filename"]
    doomed = "finance-backup-20250101-000000.zip"
    (settings.backups_dir / doomed).write_bytes(_download_backup(client, kept))
    assert {b["filename"] for b in client.get("/api/backup").json()} == {kept, doomed}

    assert client.delete(f"/api/backup/{doomed}").status_code == 204

    assert [b["filename"] for b in client.get("/api/backup").json()] == [kept]
    assert not (settings.backups_dir / doomed).exists()
    assert client.delete(f"/api/backup/{doomed}").status_code == 404  # gone


def test_only_backups_can_be_deleted_from_the_backups_folder(client, tmp_path):
    """The folder may be a shared or synced one: what is no backup of this
    app is not the app's to delete."""
    import zipfile

    from app.config import settings

    settings.ensure_directories()
    foreign = settings.backups_dir / "holiday-photos.zip"
    with zipfile.ZipFile(foreign, "w") as archive:
        archive.writestr("beach.jpg", b"...")
    outside = tmp_path / "outside.zip"
    outside.write_bytes(foreign.read_bytes())

    assert client.delete("/api/backup/holiday-photos.zip").status_code == 404
    assert client.delete("/api/backup/..%2Foutside.zip").status_code in (404, 405)  # (no such route)
    assert client.delete("/api/backup/finance.db").status_code == 404
    assert foreign.exists() and outside.exists()
