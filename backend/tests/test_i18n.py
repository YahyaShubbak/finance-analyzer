"""Messages in the UI's language (app.i18n): the German catalog covers
every message, and the request's Accept-Language decides the language."""
from __future__ import annotations

import ast
import io
import re
import string
from pathlib import Path

import pytest

from app.i18n import parse_accept_language, tr, use_language
from app.i18n_de import DE
from app.normalization.review import REVIEW_REASONS, review_reason_text

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _tr_messages() -> dict[str, str]:
    """Every literal passed to tr() in the app -> where it is used."""
    found: dict[str, str] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr" \
                    and node.args and isinstance(node.args[0], ast.Constant):
                found.setdefault(node.args[0].value, f"{path.relative_to(APP_DIR)}:{node.lineno}")
    return found


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}


def test_every_message_has_a_german_translation():
    messages = _tr_messages()
    assert len(messages) > 80  # the scan really finds the calls
    missing = {message: where for message, where in messages.items() if message not in DE}
    assert not missing
    for reason in REVIEW_REASONS:  # stored in English, translated on output
        assert reason in DE


def test_catalog_has_no_unused_entries():
    used = set(_tr_messages()) | set(REVIEW_REASONS)
    assert sorted(set(DE) - used) == []


@pytest.mark.parametrize("message", sorted(DE))
def test_translation_uses_the_same_placeholders(message):
    assert _placeholders(DE[message]) == _placeholders(message)


def test_no_user_facing_f_strings_left_untranslated():
    """Guard against new messages bypassing tr(): an exception or HTTP
    detail built from a plain (f-)string literal."""
    pattern = re.compile(r'(?:HTTPException\([^)]*detail=|(?:Error|Exception)\()f?"[A-Z a-z]')
    offenders = []
    for path in sorted(APP_DIR.rglob("*.py")):
        # legacy_migration.py: its messages appear in the (English) installer
        # window, never in the browser.
        if path.name in {"security.py", "__main__.py", "migrate.py", "env.py", "legacy_migration.py"} \
                or "migrations" in path.parts:
            continue  # messages for developers / non-browser clients
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(APP_DIR)}:{number}: {line.strip()}")
    assert offenders == []


@pytest.mark.parametrize(("header", "expected"), [
    (None, "en"),
    ("", "en"),
    ("de", "de"),
    ("de-DE,de;q=0.9,en;q=0.8", "de"),
    ("en-GB,en;q=0.9,de;q=0.8", "en"),
    ("fr-FR,de;q=0.5,en;q=0.7", "en"),
    ("fr-FR,de;q=0.5", "de"),
    ("de;q=0, en", "en"),
    ("fr", "en"),
])
def test_parse_accept_language(header, expected):
    assert parse_accept_language(header) == expected


def test_tr_follows_the_current_language():
    assert tr("Row {row}: missing date.", row=3) == "Row 3: missing date."
    with use_language("de"):
        assert tr("Row {row}: missing date.", row=3) == "Zeile 3: Datum fehlt."
        assert review_reason_text(REVIEW_REASONS[1]) == "Die Kategorie konnte nicht sicher bestimmt werden."
    assert tr("Row {row}: missing date.", row=3) == "Row 3: missing date."


def test_api_answers_in_the_requested_language(client):
    german = client.patch("/api/accounts/99999", json={"name": "x"}, headers={"Accept-Language": "de-DE,de;q=0.9"})
    assert german.status_code == 404
    assert german.json()["detail"] == "Konto nicht gefunden"
    english = client.patch("/api/accounts/99999", json={"name": "x"})
    assert english.json()["detail"] == "Account not found"


def test_validation_messages_are_translated(client):
    r = client.post("/api/accounts", json={"name": "Giro", "account_type": "checking", "iban": "DE00 1234"},
                    headers={"Accept-Language": "de"})
    assert r.status_code == 422
    assert "keine gültige IBAN" in r.text or "IBAN-Prüfziffern" in r.text


def test_import_messages_and_review_reasons_follow_the_language(client):
    account = client.post("/api/accounts", json={"name": "Giro", "account_type": "checking"}).json()
    csv = b"Datum;Verwendungszweck;Betrag\n01.09.2026;Irgendwas Unbekanntes;-12,00\n02.09.2026;;\n"
    files = {"file": ("giro.csv", io.BytesIO(csv), "text/csv")}
    de = {"Accept-Language": "de"}
    preview = client.post("/api/imports/preview", files=files, data={"account_id": account["id"]}, headers=de)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    messages = [i["message"] for i in body["issues"]]
    assert any(m.startswith("Zeile ") for m in messages), messages

    commit = client.post("/api/imports/commit", json={"staging_id": body["staging_id"], "account_id": account["id"]},
                         headers=de)
    assert commit.status_code == 200, commit.text
    reviewed = client.get("/api/transactions", params={"needs_review": True}, headers=de).json()["items"]
    assert reviewed and reviewed[0]["review_reason"] in set(DE.values())
    # stored in English, so switching the language changes it too
    english = client.get("/api/transactions", params={"needs_review": True}).json()["items"]
    assert english[0]["review_reason"] in REVIEW_REASONS
