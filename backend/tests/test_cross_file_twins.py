"""The same card bookings from the PDF statement and from the export are one
booking each, whichever comes first. Invented data."""
from __future__ import annotations

import io

from tests.pdf_fixtures import write_text_pdf

STATEMENT = [
    "Credit Card Statement", "VISA ending 1234", "Statement Period: 01.03.2026 - 31.03.2026",
    "02.03.2026 Buchladen Beispiel 40.00 EUR",
    "05.03.2026 Kiosk Muster 4.00 EUR",
    "06.03.2026 Kiosk Muster 4.00 EUR",
    "Statement Total: 48.00 EUR",
]
# the export prints the booking date: a day or two after the purchase
EXPORT = (b"Datum,Beschreibung,Betrag\n"
          b"2026-03-03,Buchladen Beispiel,-40.00\n"
          b"2026-03-07,Kiosk Muster,-4.00\n"
          b"2026-03-08,Kiosk Muster,-4.00\n"
          b"2026-03-20,Fahrradladen Beispiel,-25.00\n")


def _import(client, account, name, content, kind):
    r = client.post("/api/imports/preview", data={"account_id": account},
                    files={"file": (name, io.BytesIO(content), kind)})
    preview = r.json()
    commit = client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": account})
    assert commit.status_code == 200, commit.text
    return preview, commit.json()


def _expenses(client):
    items = client.get("/api/transactions", params={"page_size": 100}).json()["items"]
    return sorted(-t["amount_minor"] for t in items if not t["is_duplicate"] and t["amount_minor"] < 0)


def test_export_after_the_statement_completes_it(client, tmp_path):
    card = client.post("/api/accounts", json={"name": "Karte", "account_type": "credit_card"}).json()["id"]
    pdf = write_text_pdf(tmp_path / "m.pdf", STATEMENT)
    _import(client, card, "m.pdf", pdf.read_bytes(), "application/pdf")
    preview, commit = _import(client, card, "export.csv", EXPORT, "text/csv")
    assert preview["exact_duplicate_count"] == 3 and preview["new_count"] == 1
    assert commit["transactions_created"] == 1
    assert _expenses(client) == [400, 400, 2500, 4000]  # each purchase once, the export's extra one added


def test_statement_after_the_export_completes_it(client, tmp_path):
    card = client.post("/api/accounts", json={"name": "Karte", "account_type": "credit_card"}).json()["id"]
    _import(client, card, "export.csv", EXPORT, "text/csv")
    pdf = write_text_pdf(tmp_path / "m.pdf", STATEMENT)
    preview, _commit = _import(client, card, "m.pdf", pdf.read_bytes(), "application/pdf")
    assert preview["exact_duplicate_count"] == 3
    assert _expenses(client) == [400, 400, 2500, 4000]


def test_twins_imported_before_are_merged_once(client, tmp_path, monkeypatch):
    """Imported by an older version: both kept. On start-up they become one;
    removing the file that holds the kept one lets the other count again."""
    from app.config import settings
    from app.db.session import session_scope
    from app.services import duplicate_preview_service
    from app.services.twin_merge import TWINS_MARKER, merge_cross_file_twins

    card = client.post("/api/accounts", json={"name": "Karte", "account_type": "credit_card"}).json()["id"]
    with monkeypatch.context() as old_version:  # twins from the other kind of file not recognized
        old_version.setattr(duplicate_preview_service, "_twin_from_other_file", lambda *args, **kwargs: None)
        pdf = write_text_pdf(tmp_path / "m.pdf", STATEMENT)
        _p, pdf_commit = _import(client, card, "m.pdf", pdf.read_bytes(), "application/pdf")
        _import(client, card, "export.csv", EXPORT, "text/csv")
    assert _expenses(client) == [400, 400, 400, 400, 2500, 4000, 4000]  # counted twice

    (settings.data_dir / TWINS_MARKER).unlink(missing_ok=True)
    with session_scope() as session:
        assert merge_cross_file_twins(session) == 3
        assert merge_cross_file_twins(session) == 0  # once per version
    assert _expenses(client) == [400, 400, 2500, 4000]

    assert client.delete(f"/api/imports/{pdf_commit['import_id']}").status_code == 200
    assert _expenses(client) == [400, 400, 2500, 4000]  # the export's bookings count again
