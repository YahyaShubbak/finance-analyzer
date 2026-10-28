"""The import review: the original next to what was read. Invented data."""
from __future__ import annotations

import io

from tests.pdf_fixtures import write_table_pdf, write_text_pdf


def _account(client, name="Karte", account_type="credit_card"):
    return client.post("/api/accounts", json={"name": name, "account_type": account_type}).json()["id"]


STATEMENT = [
    "Credit Card Statement", "VISA ending 1234", "Statement Period: 01.03.2026 - 31.03.2026",
    "02.03.2026 Restaurant Beispiel 40.00 EUR",
    "05.03.2026 Buchhandlung Muster 12.50 EUR",
    "Statement Total: 52.50 EUR",
]


def _preview(client, path, account_id=None):
    data = {"account_id": account_id} if account_id else {}
    r = client.post("/api/imports/preview", files={"file": (path.name, io.BytesIO(path.read_bytes()), "application/pdf")}, data=data)
    assert r.status_code == 200, r.text
    return r.json()


def test_each_booking_knows_where_it_is_printed(client, tmp_path):
    card = _account(client)
    preview = _preview(client, write_text_pdf(tmp_path / "s.pdf", STATEMENT), card)
    assert preview["page_count"] == 1
    for tx in preview["transactions"]:
        loc = tx["location"]
        assert loc["page"] == 0 and loc["x1"] > loc["x0"] and loc["y1"] > loc["y0"]
    booking_lines = [line for line in preview["layout_lines"] if line["role"] == "booking"]
    assert [line["text"][:10] for line in booking_lines] == ["02.03.2026", "05.03.2026"]
    assert preview["review_reasons"] == ["new_kind"]  # the first file of its kind on this account


def test_page_images_are_served_only_for_staged_and_imported_pdfs(client, tmp_path):
    card = _account(client)
    preview = _preview(client, write_text_pdf(tmp_path / "s.pdf", STATEMENT), card)
    r = client.get(f"/api/imports/staging/{preview['staging_id']}/pages/0")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    assert client.get(f"/api/imports/staging/{preview['staging_id']}/pages/5").status_code == 404
    assert client.get("/api/imports/staging/..%2F..%2Fetc/pages/0").status_code in (404, 422)
    commit = client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": card}).json()
    assert client.get(f"/api/imports/{commit['import_id']}/pages/0").status_code == 200


def test_lines_are_labelled_with_what_the_reading_made_of_them():
    from app.importers.pdf_importer import _layout_lines

    text = "\n".join([
        "Kontoauszug",
        "02.03.2026 Restaurant Beispiel 40,00 -",       # booking (index 1)
        "02.03.2026 Kartenzahlung Ref. 12,00 x",         # right under it: part of it
        "Alter Kontostand 100,00",
        "09.03.2026 Kiosk Beispiel 12,00 ??",            # dated with an amount, not read
    ])
    box = lambda y: {"page": 0, "x0": 10.0, "y0": y, "x1": 200.0, "y1": y + 10}  # noqa: E731
    geometry = [box(0), box(20), box(31), box(60), box(90)]
    roles = [line["role"] for line in _layout_lines(text, geometry, {1})]
    assert roles == ["text", "booking", "detail", "balance", "unreadable"]


def test_dont_ask_again_lets_a_kind_of_file_import_itself(client, tmp_path):
    """A file recognized only by its format needs a click — unless the user
    checked this kind of file before and said "don't ask again"."""
    card = _account(client, "Karte 1")
    _account(client, "Karte 2")
    no_number = [line.replace("VISA ending 1234", "VISA Karte") for line in STATEMENT]  # recognized by its format only
    first = _preview(client, write_text_pdf(tmp_path / "m.pdf", no_number), card)
    r = client.post("/api/imports/commit", json={"staging_id": first["staging_id"], "account_id": card, "verified": True})
    assert r.status_code == 200
    april = [line.replace(".03.2026", ".04.2026") for line in no_number]
    second = _preview(client, write_text_pdf(tmp_path / "a.pdf", april))
    assert second["account_id"] == card and second["account_recognized"] == "format"
    assert second["auto_import"] is True and second["review_reasons"] == []


# --- teaching the reader a layout it doesn't know ---------------------------------

def _unknown_layout(path, month="05"):
    """A statement no built-in reader understands: unsigned amounts are
    purchases, credits carry a trailing "+", points lines between bookings."""
    return write_table_pdf(path, [
        [(40, "Umsatzaufstellung Beispielhaus", "l")],
        [(40, "Kundennummer 4711", "l")],
        [],
        [(40, "Datum", "l"), (150, "Vorgang", "l"), (470, "Betrag", "r")],
        [(40, f"03.{month}.2026", "l"), (150, "Bäckerei Sonnenschein", "l"), (470, "4,80", "r")],
        [(150, "Filiale Nord", "l")],
        [(40, "+5 BEISPIEL PUNKTE", "l")],
        [(40, f"07.{month}.2026", "l"), (150, "Gutschrift Rückgabe", "l"), (470, "20,00+", "r")],
        [(40, f"12.{month}.2026", "l"), (150, "Tankstelle Am Ring", "l"), (470, "61,23", "r")],
        [(40, "+61 BEISPIEL PUNKTE", "l")],
        [],
        [(40, "Offener Betrag", "l"), (470, "46,03", "r")],
    ])


def _template_from(preview):
    """What the review's teach mode sends: the example line's word positions."""
    example = next(line for line in preview["layout_lines"] if line["text"].startswith("03."))
    words = example["words"]
    return {
        "columns": {
            "date": [words[0]["x0"], words[0]["x1"]],
            "text": [words[1]["x0"], words[-2]["x1"]],
            "amount": [words[-1]["x0"], words[-1]["x1"]],
        },
        "sign_rule": "unsigned_is_expense",
        "ignore": ["+5 BEISPIEL PUNKTE"],
        "labels": {"total": "Offener Betrag"},
        "document_type": "credit_card_statement",
    }


def _upload(client, path, account_id=None):
    data = {"account_id": account_id} if account_id else {}
    r = client.post("/api/imports/preview", files={"file": (path.name, io.BytesIO(path.read_bytes()), "application/pdf")},
                    data=data)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_taught_template_reads_an_unknown_layout(client, tmp_path):
    card = _account(client)
    preview = _upload(client, _unknown_layout(tmp_path / "u.pdf"))
    assert preview["transaction_count"] == 0 and "no_bookings" in preview["review_reasons"]

    r = client.post(f"/api/imports/{preview['staging_id']}/reparse",
                    json={"options": {"pdf_template": _template_from(preview)}})  # no account chosen yet
    assert r.status_code == 200, r.text
    taught = r.json()
    assert taught["detected_layout"] == "user_template"
    got = [(t["parsed_date"], t["original_description"], t["parsed_amount_minor"]) for t in taught["transactions"]]
    assert got == [
        ("2026-05-03", "Bäckerei Sonnenschein", -480),
        ("2026-05-07", "Gutschrift Rückgabe", 2000),
        ("2026-05-12", "Tankstelle Am Ring", -6123),
    ]
    # the points lines are ignored ("+61 ..." is the same line with another number), the branch is a detail
    assert taught["transactions"][0]["details"] == "Filiale Nord"
    assert taught["transactions"][2]["details"] is None
    assert taught["statement_total_minor"] == 4603
    assert not any(i["severity"] == "error" for i in taught["issues"])

    r = client.post(f"/api/imports/{preview['staging_id']}/reparse",
                    json={"account_id": card, "options": {"pdf_template": _template_from(preview)}})
    assert r.status_code == 200
    r = client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": card, "verified": True})
    assert r.status_code == 200, r.text
    assert r.json()["transactions_created"] == 3

    # the next file of this kind is read with the template by itself
    june = _upload(client, _unknown_layout(tmp_path / "j.pdf", "06"))
    assert june["account_id"] == card and june["detected_layout"] == "user_template"
    assert [t["parsed_amount_minor"] for t in june["transactions"]] == [-480, 2000, -6123]
    assert june["auto_import"] is True


def test_a_malformed_template_is_refused(client, tmp_path):
    preview = _upload(client, _unknown_layout(tmp_path / "u.pdf"))
    for bad in ({"columns": {"date": [1, "x"]}}, {"columns": {"amount": [1e9, 2]}},
                {"columns": {}, "sign_rule": "guess"}, {"columns": {"date": [1, 2]}, "ignore": ["x" * 500]}):
        r = client.post(f"/api/imports/{preview['staging_id']}/reparse", json={"options": {"pdf_template": bad}})
        assert r.status_code == 422, bad
    # date and amount are needed: said so, no crash
    r = client.post(f"/api/imports/{preview['staging_id']}/reparse",
                    json={"options": {"pdf_template": {"columns": {"date": [40, 85]}}}})
    assert r.status_code == 200 and any(i["severity"] == "error" for i in r.json()["issues"])


def test_files_uploaded_together_learn_what_the_first_one_taught(client, tmp_path):
    """Both files are read on upload, before the user teaches the first; read
    again afterwards, the second one is read with the template and may
    import itself."""
    card = _account(client)
    may = _upload(client, _unknown_layout(tmp_path / "may.pdf", "05"))
    june = _upload(client, _unknown_layout(tmp_path / "june.pdf", "06"))
    assert june["transaction_count"] == 0 and june["account_id"] is None

    client.post(f"/api/imports/{may['staging_id']}/reparse",
                json={"account_id": card, "options": {"pdf_template": _template_from(may)}})
    r = client.post("/api/imports/commit", json={"staging_id": may["staging_id"], "account_id": card, "verified": True})
    assert r.status_code == 200, r.text

    again = client.post(f"/api/imports/{june['staging_id']}/recognize")
    assert again.status_code == 200, again.text
    june = again.json()
    assert june["account_id"] == card and june["detected_layout"] == "user_template"
    assert [t["parsed_amount_minor"] for t in june["transactions"]] == [-480, 2000, -6123]
    assert june["auto_import"] is True and june["review_reasons"] == []
    assert client.post("/api/imports/0123456789abcdef0123456789abcdef/recognize").status_code == 404
