"""A kind of file imported before goes to its account without asking, and
is imported without confirmation when its preview shows nothing to check.
All file contents are invented."""
from __future__ import annotations

import io

from sqlmodel import Session, select

from app.db.models import ImportRecord

GIRO_IBAN = "DE89370400440532013000"


def _account(client, name, account_type="checking", iban=None):
    body = {"name": name, "account_type": account_type}
    if iban:
        body["iban"] = iban
    r = client.post("/api/accounts", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _preview(client, name, content: bytes, account_id=None):
    data = {"account_id": account_id} if account_id is not None else {}
    r = client.post("/api/imports/preview", files={"file": (name, io.BytesIO(content), "text/csv")}, data=data)
    assert r.status_code == 200, r.text
    return r.json()


def _commit(client, preview, account_id=None, auto=False):
    return client.post("/api/imports/commit", json={
        "staging_id": preview["staging_id"], "account_id": account_id or preview["account_id"], "auto": auto,
    })


def _export(month: int, *rows: str) -> bytes:
    body = "\n".join(rows) or f"2026-{month:02d}-03,Baeckerei Muster,-3.{month:02d}"
    return f"Buchungstag,Verwendungszweck,Betrag\n{body}\n".encode()


def test_second_file_of_a_kind_goes_to_the_same_account_without_asking(client):
    giro = _account(client, "Giro")
    _account(client, "Tagesgeld", "savings")
    first = _preview(client, "march.csv", _export(3))
    assert first["account_id"] is None  # never seen: the user chooses
    first = _preview(client, "march.csv", _export(3), giro)
    assert first["auto_import"] is False  # chosen by hand: confirmed by hand
    assert _commit(client, first).status_code == 200

    second = _preview(client, "april.csv", _export(4))
    assert (second["account_id"], second["account_name"], second["account_recognized"]) == (giro, "Giro", "history")
    assert second["auto_import"] is True and second["new_count"] == 1
    r = _commit(client, second, auto=True)
    assert r.status_code == 200, r.text and r.json()["transactions_created"] == 1


def test_a_kind_of_file_imported_into_two_accounts_is_not_guessed(client):
    a, b = _account(client, "Giro A"), _account(client, "Giro B")
    assert _commit(client, _preview(client, "a.csv", _export(3), a)).status_code == 200
    assert _commit(client, _preview(client, "b.csv", _export(4), b)).status_code == 200
    third = _preview(client, "c.csv", _export(5))
    assert third["account_id"] is None and third["auto_import"] is False


def test_iban_in_the_file_header_names_the_account(client):
    _account(client, "Tagesgeld", "savings")
    giro = _account(client, "Giro", iban=GIRO_IBAN)
    content = (b"Kontoauszug;;\nIBAN;DE89 3704 0044 0532 0130 00;\n;;\n"
               b"Buchungstag;Verwendungszweck;Betrag\n03.03.2026;Baeckerei Muster;-3,20\n")
    preview = _preview(client, "konto.csv", content)
    assert (preview["account_id"], preview["account_recognized"]) == (giro, "iban")
    assert preview["auto_import"] is True


def test_another_card_of_the_same_issuer_is_not_taken_for_the_first(client):
    first_card = _account(client, "Karte 1", "credit_card")
    _account(client, "Karte 2", "credit_card")

    def statement(card_number, day):
        return (f"Umsaetze;;\nKarte;{card_number};\n;;\n"
                f"Datum;Beschreibung;Betrag\n{day:02d}.03.2026;Tankstelle Beispiel;-4{day},00\n").encode()

    assert _commit(client, _preview(client, "k1.csv", statement("xxxx xxxx xxxx 1234", 1), first_card)).status_code == 200
    same_card = _preview(client, "k1b.csv", statement("xxxx xxxx xxxx 1234", 2))
    assert same_card["account_id"] == first_card and same_card["auto_import"] is True
    other_card = _preview(client, "k2.csv", statement("xxxx xxxx xxxx 5678", 3))
    assert other_card["account_id"] is None


def test_the_previous_files_settings_are_reused(client):
    """A card export listing purchases as positive numbers is inverted —
    with a warning the first time, silently once the user has accepted it."""
    card = _account(client, "Amex", "credit_card")
    rows = ("2026-03-02,Restaurant Beispiel,25.00", "2026-03-05,Buchhandlung Beispiel,12.50",
            "2026-03-09,Zahlung erhalten besten Dank,-100.00")
    first = _preview(client, "amex-march.csv", _export(3, *rows), card)
    assert first["options"]["invert_signs"] is True and first["warning_count"] == 1
    assert _commit(client, first).status_code == 200

    rows = ("2026-04-02,Restaurant Beispiel,30.00", "2026-04-05,Kino Beispiel,9.50", "2026-04-09,Zahlung erhalten besten Dank,-37.50")
    second = _preview(client, "amex-april.csv", _export(4, *rows))
    assert second["account_id"] == card and second["options"]["invert_signs"] is True
    assert second["warning_count"] == 0 and second["auto_import"] is True
    assert sorted(t["parsed_amount_minor"] for t in second["transactions"]) == [-3000, -950, 3750]


def test_warnings_and_possible_duplicates_need_the_user(client):
    giro = _account(client, "Giro")
    assert _commit(client, _preview(client, "march.csv", _export(3), giro)).status_code == 200
    # a row that can't be read: recognized, but shown for confirmation
    unreadable = _preview(client, "april.csv", _export(4, "2026-04-03,Baeckerei Muster,-3.04", "kein Datum,Kiosk,-1.00"))
    assert unreadable["account_id"] == giro and unreadable["auto_import"] is False
    # the same booking again with another text: a possible duplicate
    possible = _preview(client, "march-again.csv", _export(3, "2026-03-03,Baeckerei Muster Filiale 2,-3.03"))
    assert possible["possible_duplicate_count"] == 1 and possible["auto_import"] is False


def test_auto_import_is_refused_when_duplicates_appeared_meanwhile(client):
    giro = _account(client, "Giro")
    assert _commit(client, _preview(client, "march.csv", _export(3), giro)).status_code == 200
    pdf_like = _preview(client, "may.csv", _export(5, "2026-05-03,Baeckerei Muster,-3.05"))
    other = _preview(client, "may-copy.csv", _export(5, "2026-05-03,Baeckerei Muster Filiale 2,-3.05"))
    assert pdf_like["auto_import"] and other["auto_import"]
    assert _commit(client, pdf_like, auto=True).status_code == 200
    r = _commit(client, other, auto=True)
    assert r.status_code == 409 and "already imported" in r.json()["detail"]


def test_imports_from_before_are_recognized_too(client):
    import app.db.session as db_session

    giro = _account(client, "Giro")
    assert _commit(client, _preview(client, "march.csv", _export(3), giro)).status_code == 200
    with Session(db_session.engine) as session:  # as imported by an older version
        for record in session.exec(select(ImportRecord)).all():
            record.source_key, record.source_info_json = None, None
            session.add(record)
        session.commit()
    preview = _preview(client, "april.csv", _export(4))
    assert preview["account_id"] == giro and preview["auto_import"] is True


def test_a_bank_changing_its_export_format_keeps_the_account(client):
    giro = _account(client, "Giro")
    _account(client, "Tagesgeld", "savings")
    header = "Konto;DE89 3704 0044 0532 0130 00;\n;;\n"
    old_format = (header + "Buchungstag;Verwendungszweck;Betrag\n03.03.2026;Baeckerei Muster;-3,20\n").encode()
    new_format = (header + "Datum;Text;Umsatz in EUR\n03.04.2026;Baeckerei Muster;-3,40\n").encode()
    assert _commit(client, _preview(client, "march.csv", old_format, giro)).status_code == 200
    preview = _preview(client, "april.csv", new_format)
    assert (preview["account_id"], preview["account_recognized"]) == (giro, "history")


def test_an_overview_naming_several_own_accounts_falls_back_to_history(client):
    giro = _account(client, "Giro", iban=GIRO_IBAN)
    _account(client, "Tagesgeld", "savings", iban="DE02120300000000202051")
    content = (b"Finanzreport;;\nGiro;DE89 3704 0044 0532 0130 00;\nTagesgeld;DE02 1203 0000 0000 2020 51;\n;;\n"
               b"Buchungstag;Verwendungszweck;Betrag\n03.03.2026;Baeckerei Muster;-3,20\n")
    assert _preview(client, "march.csv", content)["account_id"] is None  # never imported: ask
    assert _commit(client, _preview(client, "march.csv", content, giro)).status_code == 200
    again = content.replace(b"03.03.2026;Baeckerei Muster;-3,20", b"03.04.2026;Baeckerei Muster;-3,40")
    assert _preview(client, "april.csv", again)["account_id"] == giro


def _card_pdf(tmp_path, name, month, producer):
    """A card statement written by a given version of the issuer's software."""
    import pymupdf

    from tests.pdf_fixtures import write_text_pdf

    path = write_text_pdf(tmp_path / f"raw-{name}", [
        "Credit Card Statement", "IBAN NO93 8601 1117 947", f"Statement Period: 01.{month}.2026 - 28.{month}.2026",
        f"02.{month}.2026 Buchladen Beispiel 40.00 EUR", "Statement Total: 40.00 EUR",
    ])
    with pymupdf.open(path) as doc:
        doc.set_metadata({"producer": producer})
        doc.save(tmp_path / name)
    return tmp_path / name


def test_a_new_version_of_the_issuers_software_keeps_the_kind_of_file(client, tmp_path):
    """Producer "Quadient CXM AG~Inspire~15.0.739.3", later "Quadient~Inspire~16.0.759.6":
    the same kind of file. Its short Norwegian IBAN (15 characters) counts too."""
    from app.services.account_recognition import _identifiers

    assert _identifiers("IBAN NO93 8601 1117 947") == {"iban:NO9386011117947"}
    card = _account(client, "Karte", "credit_card")
    _account(client, "Andere Karte", "credit_card")
    first = _card_pdf(tmp_path, "a.pdf", "03", "Quadient CXM AG~Inspire~15.0.739.3")
    preview = _preview(client, "a.pdf", first.read_bytes(), card)
    assert client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": card,
                                                    "verified": True}).status_code == 200
    second = _card_pdf(tmp_path, "b.pdf", "04", "Quadient~Inspire~16.0.759.6")
    preview = _preview(client, "b.pdf", second.read_bytes())
    assert preview["account_id"] == card and preview["account_recognized"] == "history"
    assert preview["auto_import"] is True


def test_imported_files_are_signed_again_keeping_what_was_learned(client):
    import json

    from app.config import settings
    from app.db.session import session_scope
    from app.services.account_recognition import SIGNATURES_MARKER, refresh_signatures

    account = _account(client, "Giro")
    preview = _preview(client, "m.csv", _export(3, "2026-03-02,Kiosk Beispiel,-4.00"), account)
    assert client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": account,
                                                    "verified": True}).status_code == 200
    with session_scope() as session:
        record = session.exec(select(ImportRecord)).one()
        record.source_key = "signed-the-old-way"
        session.add(record)
        session.commit()
    (settings.data_dir / SIGNATURES_MARKER).unlink(missing_ok=True)
    with session_scope() as session:
        assert refresh_signatures(session) == 1
        assert refresh_signatures(session) == 0  # once per version
        record = session.exec(select(ImportRecord)).one()
        assert record.source_key != "signed-the-old-way" and json.loads(record.source_info_json)["verified"] is True


def _statement_pdf(tmp_path, name, card, start, end, day):
    from tests.pdf_fixtures import write_text_pdf

    return write_text_pdf(tmp_path / name, [
        "Credit Card Statement", f"Card number {card}", f"Statement Period: {start} - {end}",
        f"{day} Buchladen Beispiel 40.00 EUR", "Statement Total: 40.00 EUR",
    ])


def test_a_replaced_card_is_suggested_for_its_account(client, tmp_path):
    """The bank sends a new card (a new number): its statements come after
    the old card's — the account is suggested, the user confirms once. A
    second card running side by side (periods overlapping) is asked about."""
    card = _account(client, "Karte", "credit_card")
    _account(client, "Andere Karte", "credit_card")
    old = _statement_pdf(tmp_path, "m.pdf", "xxxx xxxx xxxx 1234", "01.03.2026", "31.03.2026", "02.03.2026")
    preview = _preview(client, "m.pdf", old.read_bytes(), card)
    assert client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": card,
                                                    "verified": True}).status_code == 200

    new = _statement_pdf(tmp_path, "a.pdf", "xxxx xxxx xxxx 5678", "01.04.2026", "30.04.2026", "02.04.2026")
    replaced = _preview(client, "a.pdf", new.read_bytes())
    assert replaced["account_id"] == card and replaced["account_recognized"] == "replaced"
    assert replaced["auto_import"] is False  # confirmed once
    assert client.post("/api/imports/commit", json={"staging_id": replaced["staging_id"], "account_id": card}).status_code == 200
    may = _statement_pdf(tmp_path, "c.pdf", "xxxx xxxx xxxx 5678", "01.05.2026", "31.05.2026", "02.05.2026")
    following = _preview(client, "c.pdf", may.read_bytes())
    assert following["account_id"] == card and following["account_recognized"] == "history"
    assert following["auto_import"] is True  # the new card is known now

    side_by_side = _statement_pdf(tmp_path, "b.pdf", "xxxx xxxx xxxx 9999", "15.03.2026", "14.04.2026", "16.03.2026")
    assert _preview(client, "b.pdf", side_by_side.read_bytes())["account_id"] is None


def test_another_card_is_not_imported_into_the_confirmed_one(client, tmp_path):
    """"VISA ending 5678" is another card than "VISA ending 1234" — even after
    "don't ask again" for this kind of file, it is asked about."""
    card = _account(client, "Karte 1", "credit_card")
    _account(client, "Karte 2", "credit_card")
    first = _statement_pdf(tmp_path, "a.pdf", "VISA ending 1234", "01.03.2026", "31.03.2026", "02.03.2026")
    preview = _preview(client, "a.pdf", first.read_bytes(), card)
    assert client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": card,
                                                    "verified": True}).status_code == 200
    other = _statement_pdf(tmp_path, "b.pdf", "VISA ending 5678", "01.03.2026", "31.03.2026", "03.03.2026")
    preview = _preview(client, "b.pdf", other.read_bytes())
    assert preview["account_id"] is None and preview["auto_import"] is False


def test_two_unknown_layouts_keep_their_own_taught_reader(client, tmp_path):
    from tests.pdf_fixtures import write_table_pdf
    from tests.test_import_review import _template_from, _unknown_layout

    def other_bank(path):
        return write_table_pdf(path, [
            [(40, "Kontoliste Musterkasse", "l")], [],
            [(40, "Tag", "l"), (200, "Text", "l"), (520, "Wert", "r")],
            [(40, "03.05.2026", "l"), (200, "Werkstatt Beispiel", "l"), (520, "-55,00", "r")],
        ])

    giro = _account(client, "Kundenkarte", "credit_card")  # the first layout is taught as a card statement
    spar = _account(client, "Spar", "savings")
    first = _preview(client, "u.pdf", _unknown_layout(tmp_path / "u.pdf").read_bytes())
    client.post(f"/api/imports/{first['staging_id']}/reparse",
                json={"account_id": giro, "options": {"pdf_template": _template_from(first)}})
    assert client.post("/api/imports/commit", json={"staging_id": first["staging_id"], "account_id": giro}).status_code == 200

    second = _preview(client, "o.pdf", other_bank(tmp_path / "o.pdf").read_bytes())
    assert second["account_id"] is None  # another bank: not read with the first one's template
    words = next(line for line in second["layout_lines"] if line["text"].startswith("03."))["words"]
    template = {"columns": {"date": [words[0]["x0"], words[0]["x1"]], "amount": [words[-1]["x0"], words[-1]["x1"]]}}
    client.post(f"/api/imports/{second['staging_id']}/reparse", json={"account_id": spar, "options": {"pdf_template": template}})
    assert client.post("/api/imports/commit", json={"staging_id": second["staging_id"], "account_id": spar}).status_code == 200

    june = _preview(client, "j.pdf", _unknown_layout(tmp_path / "j.pdf", "06").read_bytes())
    assert june["account_id"] == giro and june["detected_layout"] == "user_template"
    assert [t["parsed_amount_minor"] for t in june["transactions"]] == [-480, 2000, -6123]
