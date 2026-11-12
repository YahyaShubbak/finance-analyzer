"""What an imported row has to do with a booking that is not its own is kept
in columns (RawTransaction.duplicate_of_transaction_id, kept_by_user) — not
inside the JSON of the file's extra columns, searched for as text. Invented
data."""
from __future__ import annotations

import io

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.db.models import ImportRecord, RawTransaction, Transaction
from tests.pdf_fixtures import write_text_pdf

STATEMENT = [
    "Credit Card Statement", "VISA ending 1234", "Statement Period: 01.03.2026 - 31.03.2026",
    "02.03.2026 Buchladen Beispiel 40.00 EUR",
    "05.03.2026 Kiosk Muster 4.00 EUR",
    "Statement Total: 44.00 EUR",
]
# the card's export: the booking date (a day later), and the merchant's town
EXPORT = (b"Datum,Beschreibung,Betrag,Ort\n"
          b"2026-03-03,Buchladen Beispiel,-40.00,Barcelona\n"
          b"2026-03-06,Kiosk Muster,-4.00,Bochum\n")
COFFEE = b"Date,Description,Amount\n2026-01-02,Coffee Shop,-4.50\n"


def _account(client, name="Giro", account_type="checking") -> int:
    r = client.post("/api/accounts", json={"name": name, "account_type": account_type, "currency": "EUR"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _preview(client, account, name, content, kind="text/csv") -> dict:
    r = client.post("/api/imports/preview", data={"account_id": account}, files={"file": (name, io.BytesIO(content), kind)})
    assert r.status_code == 200, r.text
    return r.json()


def _import(client, account, name, content, kind="text/csv", decisions: dict[int, str] | None = None) -> dict:
    preview = _preview(client, account, name, content, kind)
    payload = {"staging_id": preview["staging_id"], "account_id": account}
    if decisions:
        payload["row_decisions"] = [{"source_row_index": row, "decision": d} for row, d in decisions.items()]
    commit = client.post("/api/imports/commit", json=payload)
    assert commit.status_code == 200, commit.text
    return commit.json()


def _rows(session, import_id) -> list[RawTransaction]:
    return list(session.exec(
        select(RawTransaction).where(RawTransaction.import_id == import_id).order_by(RawTransaction.source_row_index)
    ).all())


def _bookings(client) -> list[dict]:
    return client.get("/api/transactions", params={"page_size": 100}).json()["items"]


def test_a_skipped_row_names_its_booking_and_still_tells_its_place(client, tmp_path):
    """The statement first, then the export of the same card: the export's
    rows become no bookings, name the ones they are — and tell their town."""
    from app.db.session import session_scope

    card = _account(client, "Karte", "credit_card")
    pdf = write_text_pdf(tmp_path / "m.pdf", STATEMENT)
    _import(client, card, "m.pdf", pdf.read_bytes(), "application/pdf")
    export = _import(client, card, "export.csv", EXPORT)
    assert export["transactions_created"] == 0 and export["rows_skipped"] == 2

    bookings = {t["normalized_description"]: t for t in _bookings(client)}
    assert len(bookings) == 2
    with session_scope() as session:
        rows = _rows(session, export["import_id"])
        assert [r.duplicate_of_transaction_id for r in rows] == [
            bookings["Buchladen Beispiel"]["id"], bookings["Kiosk Muster"]["id"],
        ]
        # the JSON holds what the file said, nothing of the app's
        assert all("_duplicate_of" not in r.extra_fields_json and '"Ort"' in r.extra_fields_json for r in rows)
        assert not any(r.kept_by_user for r in rows)
    assert (bookings["Buchladen Beispiel"]["country"], bookings["Buchladen Beispiel"]["city"]) == ("ES", "Barcelona")
    assert (bookings["Kiosk Muster"]["country"], bookings["Kiosk Muster"]["city"]) == ("DE", "Bochum")


def test_a_row_the_user_kept_as_a_booking_of_its_own_is_marked(client):
    from app.db.session import session_scope

    account = _account(client)
    _import(client, account, "a.csv", COFFEE)
    second = _import(client, account, "b.csv", COFFEE + b"2026-01-05,Other,-1.00\n", decisions={0: "keep"})
    assert second["transactions_created"] == 2

    with session_scope() as session:
        kept, other = _rows(session, second["import_id"])
        assert kept.kept_by_user and not other.kept_by_user
        assert kept.duplicate_of_transaction_id is None
        assert "_kept_by_user" not in (kept.extra_fields_json or "")


def test_bookings_the_user_kept_apart_are_not_merged_as_twins(client, tmp_path, monkeypatch):
    from app.config import settings
    from app.db.session import session_scope
    from app.services import duplicate_preview_service
    from app.services.twin_merge import TWINS_MARKER, merge_cross_file_twins

    card = _account(client, "Karte", "credit_card")
    with monkeypatch.context() as old_version:  # twins from the other kind of file not recognized: both imported
        old_version.setattr(duplicate_preview_service, "_twin_from_other_file", lambda *args, **kwargs: None)
        pdf = write_text_pdf(tmp_path / "m.pdf", STATEMENT)
        _import(client, card, "m.pdf", pdf.read_bytes(), "application/pdf")
        export = _import(client, card, "export.csv", EXPORT)
    assert len(_bookings(client)) == 4

    (settings.data_dir / TWINS_MARKER).unlink(missing_ok=True)
    with session_scope() as session:
        bookshop_row = _rows(session, export["import_id"])[0]
        bookshop_row.kept_by_user = True  # "a second purchase there, not the same one"
        session.add(bookshop_row)
        session.commit()
        assert merge_cross_file_twins(session) == 1  # the kiosk's only
    counted = sorted(-t["amount_minor"] for t in _bookings(client) if not t["is_duplicate"])
    assert counted == [400, 4000, 4000]


def test_a_row_cannot_name_a_booking_that_does_not_exist(session, checking_account):
    """Booking ids are given again after the newest booking was removed: a
    reference left behind would then name another booking."""
    record = ImportRecord(filename="a.csv", stored_path="a.csv", file_checksum="a", account_id=checking_account.id)
    session.add(record)
    session.flush()
    session.add(RawTransaction(import_id=record.id, source_row_index=0, duplicate_of_transaction_id=4711))
    with pytest.raises(IntegrityError):
        session.flush()


def _two_rows_of_one_booking(client):
    """a.csv has the booking; both rows of b.csv are it (the second one, a day
    later, by the user's word)."""
    account = _account(client)
    first = _import(client, account, "a.csv", COFFEE)
    preview = _preview(client, account, "b.csv", COFFEE + b"2026-01-03,Coffee Shop,-4.50\n")
    assert [r["status"] for r in preview["row_classifications"]] == ["exact_duplicate", "possible_duplicate"]
    commit = client.post("/api/imports/commit", json={
        "staging_id": preview["staging_id"], "account_id": account,
        "row_decisions": [{"source_row_index": 1, "decision": "skip"}],
    })
    assert commit.status_code == 200, commit.text
    assert commit.json()["transactions_created"] == 0
    return first["import_id"], commit.json()["import_id"]


def test_the_booking_moves_to_another_file_that_has_it_and_goes_with_the_last_one(client):
    from app.db.session import session_scope

    first, second = _two_rows_of_one_booking(client)
    booking = _bookings(client)[0]["id"]
    with session_scope() as session:
        assert [r.duplicate_of_transaction_id for r in _rows(session, second)] == [booking, booking]

    # the file it came from is removed: the booking stays, now as the other file's first row
    assert client.delete(f"/api/imports/{first}").status_code == 200
    assert [t["id"] for t in _bookings(client)] == [booking]
    with session_scope() as session:
        own, still_pointing = _rows(session, second)
        assert session.get(Transaction, booking).raw_transaction_id == own.id
        assert (own.duplicate_of_transaction_id, still_pointing.duplicate_of_transaction_id) == (None, booking)

    # ... and with that file, it goes — although a row of the file still named it
    removed = client.delete(f"/api/imports/{second}")
    assert removed.status_code == 200, removed.text
    assert _bookings(client) == []
    with session_scope() as session:
        assert session.exec(select(RawTransaction)).all() == []


def test_reset_works_with_rows_that_name_bookings(client):
    _two_rows_of_one_booking(client)
    r = client.post("/api/system/reset", json={"confirm": "RESET"})
    assert r.status_code == 200, r.text
    assert _bookings(client) == [] and client.get("/api/imports").json() == []


def test_a_statement_counts_its_purchases_that_came_from_the_export_first(client, tmp_path):
    """None of the statement's rows becomes a booking — it still adds up."""
    card = _account(client, "Karte", "credit_card")
    _import(client, card, "export.csv", EXPORT)
    pdf = write_text_pdf(tmp_path / "m.pdf", STATEMENT)
    statement = _import(client, card, "m.pdf", pdf.read_bytes(), "application/pdf")
    assert statement["transactions_created"] == 0 and statement["rows_skipped"] == 2

    (listed,) = client.get(f"/api/credit-cards/{card}/statements").json()
    assert (listed["statement_total_minor"], listed["transaction_count"], listed["difference_minor"]) == (4400, 2, 0)
