"""Regression tests for the local-app security guard and backup hardening
(zip slip, cross-site restore, DNS rebinding, staged/atomic restore)."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.security import check_request

_REQUIRED_TABLES = [
    "accounts", "imports", "raw_transactions", "transactions", "user_corrections",
    "merchant_rules", "category_rules", "credit_card_statements", "reconciliations",
]


# --- request guard ------------------------------------------------------------

@pytest.mark.parametrize("host", ["127.0.0.1:8420", "localhost:8420", "[::1]:8420", "localhost"])
def test_local_hosts_allowed(host):
    assert check_request("GET", {"host": host}) is None


@pytest.mark.parametrize("host", [
    "attacker.example:8420", "attacker.example", "192.168.1.5:8420", "", "[::1].evil.com:8420",
    "localhost.evil.com", "127.0.0.1@evil.com", "localhost:8420:1",
])
def test_foreign_host_rejected_even_for_reads(host):
    # DNS rebinding: the attacker's domain resolves to 127.0.0.1, but the
    # browser still sends the attacker's hostname.
    assert check_request("GET", {"host": host})[0] == 421


def test_state_change_requires_client_header():
    assert check_request("POST", {"host": "127.0.0.1:8420"})[0] == 403
    assert check_request("POST", {"host": "127.0.0.1:8420", "x-finance-client": "1"}) is None


@pytest.mark.parametrize("origin", ["https://attacker.example", "null", "http://localhost:3000"])
def test_foreign_origin_rejected(origin):
    headers = {"host": "127.0.0.1:8420", "x-finance-client": "1", "origin": origin}
    assert check_request("POST", headers)[0] == 403


def test_own_and_dev_server_origins_allowed():
    for origin in ("http://127.0.0.1:8420", "http://localhost:8420", "http://localhost:5173"):
        headers = {"host": "127.0.0.1:8420", "x-finance-client": "1", "origin": origin}
        assert check_request("DELETE", headers) is None, origin


def test_cross_site_fetch_metadata_rejected():
    headers = {"host": "127.0.0.1:8420", "x-finance-client": "1", "sec-fetch-site": "cross-site"}
    assert check_request("POST", headers)[0] == 403


def test_cross_site_multipart_restore_is_blocked(client, tmp_path):
    """A malicious page can send a multipart POST without preflight — the
    guard must stop it before the restore endpoint ever runs."""
    from app.main import app

    evil = TestClient(app, base_url="http://127.0.0.1:8420")  # no client header, foreign origin
    r = evil.post(
        "/api/backup/restore",
        headers={"Origin": "https://attacker.example"},
        files={"file": ("x.zip", b"PK\x05\x06" + b"\x00" * 18, "application/zip")},
        data={"confirm": "true"},
    )
    assert r.status_code == 403


def test_security_headers_present(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


# --- SPA fallback -------------------------------------------------------------

def test_spa_fallback_serves_index_for_client_routes(tmp_path):
    from app.main import SPAStaticFiles

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "assets" / "app-abc.js").write_text("console.log(1)")
    spa = FastAPI()
    spa.mount("/", SPAStaticFiles(directory=str(tmp_path), html=True))
    c = TestClient(spa)

    assert c.get("/transactions").text == "<html>app</html>"
    assert c.get("/reconciliation/3").text == "<html>app</html>"
    assert "immutable" in c.get("/assets/app-abc.js").headers["cache-control"]
    assert c.get("/assets/missing.js").status_code == 404
    assert c.get("/api/does-not-exist").status_code == 404


# --- backup / restore ---------------------------------------------------------

def _valid_db_bytes(tmp_path, extra_sql: str = "") -> bytes:
    path = tmp_path / "src.db"
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    for table in _REQUIRED_TABLES:
        conn.execute(f"CREATE TABLE {table} (id INTEGER)")
    if extra_sql:
        conn.executescript(extra_sql)
    conn.commit()
    conn.close()
    return path.read_bytes()


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _restore(client, payload: bytes):
    return client.post(
        "/api/backup/restore",
        files={"file": ("backup.zip", payload, "application/zip")},
        data={"confirm": "true"},
    )


@pytest.mark.parametrize("evil_name", [
    "imports/../../outside.txt",
    "imports/../outside.txt",
    "imports//etc/outside.txt",
    "/abs/outside.txt",
    "imports/..\\..\\outside.txt",
    "imports/C:/outside.txt",
])
def test_zip_slip_rejected_and_nothing_written(client, tmp_path, evil_name):
    from app.config import settings

    payload = _zip({"finance.db": _valid_db_bytes(tmp_path), "manifest.json": b"{}", evil_name: b"owned"})
    r = _restore(client, payload)

    assert r.status_code == 400
    assert "unsafe file name" in r.json()["detail"]
    for root in (tmp_path, settings.data_dir.parent, settings.imports_dir.parent):
        assert not list(root.rglob("outside.txt"))


def test_backup_from_newer_version_rejected(client, tmp_path):
    db = _valid_db_bytes(
        tmp_path, "CREATE TABLE alembic_version (version_num TEXT); INSERT INTO alembic_version VALUES ('ffffffffffff');"
    )
    r = _restore(client, _zip({"finance.db": db, "manifest.json": b"{}"}))
    assert r.status_code == 400
    assert "newer version" in r.json()["detail"]


def test_damaged_member_leaves_current_data_untouched(client, tmp_path):
    """A CRC error in a source document must be detected before the live
    database or imports are replaced."""
    from app.config import settings

    client.post("/api/accounts", json={"name": "Keep me", "account_type": "checking"})
    backup = client.post("/api/backup/create").json()
    (settings.imports_dir / "existing.csv").write_text("keep")

    good = (settings.backups_dir / backup["filename"]).read_bytes()
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(good)) as src, zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as dst:
        for info in src.infolist():
            dst.writestr(info.filename, src.read(info.filename))
        dst.writestr("imports/doc.csv", b"A" * 5000)
    damaged = bytearray(buf.getvalue())
    marker = damaged.find(b"A" * 5000)
    damaged[marker + 10] = ord("B")  # corrupt the stored bytes -> CRC mismatch on read

    r = _restore(client, bytes(damaged))
    assert r.status_code == 400
    assert [a["name"] for a in client.get("/api/accounts").json()] == ["Keep me"]
    assert (settings.imports_dir / "existing.csv").read_text() == "keep"


def test_old_schema_backup_is_migrated_on_restore(client, tmp_path):
    """Restoring a backup from an older app version must leave a database
    with the CURRENT schema — not one that breaks until the next restart."""
    from alembic import command

    from app.db.migrate import _alembic_config

    old_db = tmp_path / "old.db"
    command.upgrade(_alembic_config(f"sqlite:///{old_db}"), "c8b446ce5dd9")  # before budgets/opening balance
    payload = _zip({"finance.db": old_db.read_bytes(), "manifest.json": json.dumps({"counts": {}}).encode()})

    r = _restore(client, payload)
    assert r.status_code == 200, r.text
    assert client.get("/api/budgets").status_code == 200  # table added by a later migration
    assert client.get("/api/accounts").status_code == 200


def test_restore_upload_size_limit(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_backup_upload_bytes", 1024)
    r = _restore(client, b"x" * 4096)
    assert r.status_code == 413


def test_zip_bomb_guard(client, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_backup_uncompressed_bytes", 10_000)
    payload = _zip({"finance.db": _valid_db_bytes(tmp_path), "manifest.json": b"{}", "imports/big": b"\0" * 50_000})
    r = _restore(client, payload)
    assert r.status_code == 400
    assert "exceeds the limit" in r.json()["detail"]


# --- start-up port check ------------------------------------------------------

def test_port_check_detects_a_running_listener():
    import socket

    from app.__main__ import _port_available

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        assert not _port_available("127.0.0.1", listener.getsockname()[1])


@pytest.mark.skipif(os.name == "nt", reason="TIME_WAIT does not block bind() on Windows")
def test_port_check_ignores_connections_of_a_just_stopped_instance():
    """Restarting the app right after closing it must not report the port
    as busy: the old instance's connections linger in TIME_WAIT."""
    import socket

    from app.__main__ import _port_available

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port))
    served, _ = listener.accept()
    served.close()  # the server closes first -> its side enters TIME_WAIT
    listener.close()
    client.close()
    assert _port_available("127.0.0.1", port)


def test_backups_with_odd_manifests_are_listed_or_refused_cleanly(client, tmp_path):
    """A manifest whose counts aren't numbers must not break the backup list,
    and a restore of such a backup must answer 200 (it did happen) or refuse
    before touching anything — never 500 after the fact."""
    import json as _json
    import zipfile

    from app.config import settings

    created = client.post("/api/backup/create").json()["filename"]
    good = settings.backups_dir / created
    for name, manifest in (("odd-counts.zip", {"created_at": "x", "counts": {"accounts": "two"}}),
                           ("list-manifest.zip", ["not", "an", "object"])):
        with zipfile.ZipFile(good) as src, zipfile.ZipFile(settings.backups_dir / name, "w") as dst:
            for item in src.infolist():
                data = _json.dumps(manifest).encode() if item.filename == "manifest.json" else src.read(item)
                dst.writestr(item, data)
    listed = client.get("/api/backup")
    assert listed.status_code == 200
    assert {b["filename"] for b in listed.json()} >= {created, "odd-counts.zip"}
    r = client.post("/api/backup/odd-counts.zip/restore", data={"confirm": "true"})
    assert r.status_code in (200, 400), r.text
    assert client.get("/api/backup/%00x.zip/download").status_code == 404


def test_other_websites_cannot_read_or_embed_the_api(client):
    r = client.get("/api/accounts", headers={"Sec-Fetch-Site": "cross-site", "Origin": "http://evil.example"})
    assert r.status_code == 403
    r = client.get("/api/accounts")
    assert r.status_code == 200 and r.headers["cross-origin-resource-policy"] == "same-origin"


# --- findings of an independent security audit --------------------------------

def test_a_backup_carrying_a_trigger_is_refused(client, tmp_path):
    """A trigger would run on every later import (e.g. multiply amounts)."""
    db = _valid_db_bytes(tmp_path, "CREATE TABLE t (x); CREATE TRIGGER inflate AFTER INSERT ON t BEGIN SELECT 1; END;")
    r = _restore(client, _zip({"finance.db": db, "manifest.json": b"{}"}))
    assert r.status_code == 400 and "trigger" in r.json()["detail"].lower()


def test_a_password_protected_pdf_is_explained_not_a_crash(client, tmp_path):
    import pymupdf

    path = tmp_path / "secret.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 50), "02.03.2026 Kiosk 4.00 EUR")
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    account = client.post("/api/accounts", json={"name": "Karte", "account_type": "credit_card"}).json()["id"]
    r = client.post("/api/imports/preview", data={"account_id": account},
                    files={"file": ("secret.pdf", io.BytesIO(path.read_bytes()), "application/pdf")})
    assert r.status_code == 200
    assert any("password" in i["message"].lower() for i in r.json()["issues"])


def test_an_oversized_table_is_refused(client, monkeypatch):
    from app.importers import csv_importer

    monkeypatch.setattr(csv_importer, "MAX_TABLE_ROWS", 5)
    account = client.post("/api/accounts", json={"name": "Giro", "account_type": "checking"}).json()["id"]
    body = "Datum,Beschreibung,Betrag\n" + "".join(f"2026-03-0{d},Kiosk,-1.00\n" for d in range(1, 9))
    r = client.post("/api/imports/preview", data={"account_id": account},
                    files={"file": ("big.csv", io.BytesIO(body.encode()), "text/csv")})
    assert r.status_code == 200 and r.json()["has_errors"] and "too large" in r.json()["issues"][0]["message"].lower()


def test_input_limits(client):
    assert client.post("/api/accounts", json={"name": "x" * 101, "account_type": "checking"}).status_code == 422
    r = client.post("/api/accounts", json={"name": "Giro\x00\nKonto", "account_type": "checking"})
    assert r.status_code == 200 and r.json()["name"] == "Giro Konto"
    assert client.patch(f"/api/accounts/{r.json()['id']}", json={"opening_balance_minor": 2 ** 62}).status_code == 422
    assert client.post("/api/imports/preview", data={"options": "[" * 100_000},
                       files={"file": ("a.csv", io.BytesIO(b"x"), "text/csv")}).status_code == 422
