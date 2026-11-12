"""Bonus points printed on card statements. Invented data."""
from __future__ import annotations

import io

from app.importers.pdf_layouts.points import extract_points
from tests.pdf_fixtures import write_text_pdf


def test_points_lines_belong_to_the_booking_above_them():
    lines = [
        "Kartenabrechnung",                                   # 0
        "01.03.2026 Buchladen Beispiel 20,00 -",              # 1 booking
        "+20 SHOP PUNKTE",                                    # 2
        "+10 SHOP PRIME PUNKTE",                              # 3
        "03.03.2026 Kiosk Beispiel 4,00 -",                   # 4 booking, its points after a page break:
        "Seite 2 von 2",                                      # 5
        "+4 SHOP PUNKTE",                                     # 6
        "05.03.2026 Rückgabe Buchladen 20,00 +",              # 7 booking (refund)
        "-20 SHOP PUNKTE",                                    # 8
        "-10 SHOP PRIME PUNKTE",                              # 9
        "EINGELOESTE SHOP PUNKTE 06.03.2026 1.500 - 15,00 -",  # 10
        "alter Stand neu gesammelt eingelöst neuer Stand",    # 11
        "Shop Punkte + 2.000 + 4 - 1.500 + 504",              # 12
        "100 Shop Punkte entsprechen 1 Euro",                 # 13
    ]
    out = extract_points(lines, [1, 4, 7])
    earned = [(e.booking_row, e.points, e.note) for e in out.entries if e.kind == "earned"]
    assert earned == [(1, 20, None), (1, 10, "Prime"), (4, 4, None), (7, -20, None), (7, -10, "Prime")]
    redeemed = [e for e in out.entries if e.kind == "redeemed"]
    assert [(e.points, e.date_text, e.value_minor) for e in redeemed] == [(-1500, "2026-03-06", 1500)]
    assert out.standing == {"SHOP|PUNKTE": (2000, 4, -1500, 504)}
    assert [e.points for e in out.entries if e.kind == "balance"] == [504]
    assert out.names == {"SHOP|PUNKTE": "Shop Punkte"} and out.value_per_100 == {"SHOP|PUNKTE": 100}


def test_a_partner_programs_monthly_sum():
    lines = ["Zeitraum vom 15.02.26 bis 14.03.26", "Neu gesammelte PARTNER Punkte über Beispielkarte 120"]
    out = extract_points(lines, [])
    assert [(e.program, e.points, e.kind, e.date_text) for e in out.entries] == [("PARTNER|PUNKTE", 120, "earned", "2026-03-14")]
    assert out.names["PARTNER|PUNKTE"] == "PARTNER Punkte"


STATEMENT = [
    "Credit Card Statement", "VISA ending 1234", "Statement Period: 01.03.2026 - 31.03.2026",
    "02.03.2026 Buchladen Beispiel 40.00 EUR",
    "+40 SHOP PUNKTE",
    "05.03.2026 Buchladen Beispiel 10.00 EUR",
    "+10 SHOP PUNKTE",
    "09.03.2026 Kiosk Beispiel 5.00 EUR",
    "+5 SHOP PUNKTE",
    "EINGELOESTE SHOP PUNKTE 20.03.2026 500 - 5,00 -",
    "alter Stand neu gesammelt eingelöst neuer Stand",
    "Shop Punkte + 1.000 + 55 - 500 + 555",
    "100 Shop Punkte entsprechen 1 Euro",
    "Statement Total: 55.00 EUR",
]


def _import(client, tmp_path, lines, name="karte.pdf"):
    card = client.post("/api/accounts", json={"name": "Karte", "account_type": "credit_card"}).json()["id"]
    path = write_text_pdf(tmp_path / name, lines)
    preview = client.post("/api/imports/preview", data={"account_id": card},
                          files={"file": (name, io.BytesIO(path.read_bytes()), "application/pdf")}).json()
    assert preview["transaction_count"] == 3, preview["issues"]
    r = client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": card})
    assert r.status_code == 200, r.text
    return r.json()["import_id"]


def test_points_of_an_imported_statement(client, tmp_path):
    import_id = _import(client, tmp_path, STATEMENT)
    [program] = client.get("/api/points").json()
    assert program["name"] == "Shop Punkte" and program["value_per_100"] == 100
    assert program["balance"] == 555 and program["balance_stated"] and program["balance_value_minor"] == 555
    assert program["earned"] == 55 and program["redeemed"] == -500
    assert program["months"] == [{"month": "2026-03", "earned": 55, "redeemed": -500, "balance": 555}]
    assert program["cashback_percent"] == 1.0  # 55 points = 0.55 € on 55 € spent
    assert program["merchants"][0] == {"merchant": program["merchants"][0]["merchant"], "points": 50, "bookings": 2,
                                       "spent_minor": 5000}
    assert program["redemptions"] == [{"date": "2026-03-20", "points": -500, "value_minor": 500}]

    items = client.get("/api/transactions", params={"page_size": 10}).json()["items"]
    assert sorted(t["points"] for t in items) == [5, 10, 40]

    # the user says what a point is worth
    r = client.patch(f"/api/points/programs/{program['id']}", json={"value_per_100": 50})
    assert r.status_code == 200 and r.json()["balance_value_minor"] == 278 and r.json()["value_set_by_user"]
    assert client.patch(f"/api/points/programs/{program['id']}", json={"name": " "}).status_code == 422
    assert client.patch("/api/points/programs/999", json={"name": "x"}).status_code == 404

    # removing the statement removes its points
    assert client.delete(f"/api/imports/{import_id}").status_code == 200
    assert client.get("/api/points").json() == []


def test_points_of_statements_imported_before_are_read_on_start(client, tmp_path):
    from sqlmodel import delete

    from app.config import settings
    from app.db.models import PointsEntry
    from app.db.session import session_scope
    from app.services.points_service import POINTS_MARKER, backfill_points

    _import(client, tmp_path, STATEMENT)
    with session_scope() as session:
        session.exec(delete(PointsEntry))
        session.commit()
        assert client.get("/api/points").json() == []
        (settings.data_dir / POINTS_MARKER).unlink(missing_ok=True)
        backfill_points(session)
    [program] = client.get("/api/points").json()
    assert program["balance"] == 555 and program["earned"] == 55
    assert sorted(t["points"] for t in client.get("/api/transactions").json()["items"]) == [5, 10, 40]


def _points_statement(month, opening, earned_lines, earned_printed, redeemed, closing):
    lines = ["Credit Card Statement", "VISA ending 1234", f"Statement Period: 01.{month}.2026 - 28.{month}.2026",
             f"02.{month}.2026 Buchladen Beispiel 40.00 EUR", *earned_lines]
    if redeemed:
        lines.append(f"EINGELOESTE SHOP PUNKTE 20.{month}.2026 {redeemed} - {redeemed // 100},{redeemed % 100:02d} -")
    return lines + ["alter Stand neu gesammelt eingelöst neuer Stand",
                    f"Shop Punkte + {opening} + {earned_printed} - {redeemed} + {closing}",
                    "Statement Total: 40.00 EUR"]


def test_the_standing_follows_each_statements_printed_figures(client, tmp_path):
    """March lists only part of its points per booking (a line not read): its
    printed figures still decide; every month ends on the printed balance."""
    card = client.post("/api/accounts", json={"name": "Karte", "account_type": "credit_card"}).json()["id"]
    for month, lines in (("03", _points_statement("03", 1000, ["+40 SHOP PUNKTE"], 55, 0, 1055)),
                         ("04", _points_statement("04", 1055, ["+40 SHOP PUNKTE"], 40, 500, 595))):
        path = write_text_pdf(tmp_path / f"{month}.pdf", lines)
        preview = client.post("/api/imports/preview", data={"account_id": card},
                              files={"file": (path.name, io.BytesIO(path.read_bytes()), "application/pdf")}).json()
        assert client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": card}).status_code == 200
    [program] = client.get("/api/points").json()
    assert [(m["month"], m["balance"]) for m in program["months"]] == [("2026-03", 1055), ("2026-04", 595)]
    assert program["earned"] == 95 and program["redeemed"] == -500 and program["balance"] == 595


def test_points_reach_bookings_that_came_from_the_export_first(client, tmp_path):
    """The statement's rows are no bookings of their own then (each names the
    export's booking it is) — its points still belong to those, also when
    they are read again on start."""
    from sqlmodel import delete

    from app.config import settings
    from app.db.models import PointsEntry
    from app.db.session import session_scope
    from app.services.points_service import POINTS_MARKER, backfill_points

    card = client.post("/api/accounts", json={"name": "Karte", "account_type": "credit_card"}).json()["id"]
    export = (b"Datum,Beschreibung,Betrag\n2026-03-03,Buchladen Beispiel,-40.00\n"
              b"2026-03-06,Buchladen Beispiel,-10.00\n2026-03-10,Kiosk Beispiel,-5.00\n")
    path = write_text_pdf(tmp_path / "karte.pdf", STATEMENT)
    for name, content, kind in (("export.csv", export, "text/csv"), ("karte.pdf", path.read_bytes(), "application/pdf")):
        preview = client.post("/api/imports/preview", data={"account_id": card},
                              files={"file": (name, io.BytesIO(content), kind)}).json()
        commit = client.post("/api/imports/commit", json={"staging_id": preview["staging_id"], "account_id": card})
        assert commit.status_code == 200, commit.text
    assert commit.json()["transactions_created"] == 0  # all three were there

    def points():
        return sorted(t["points"] or 0 for t in client.get("/api/transactions").json()["items"])

    assert points() == [5, 10, 40]
    with session_scope() as session:
        session.exec(delete(PointsEntry))
        session.commit()
        assert points() == [0, 0, 0]
        (settings.data_dir / POINTS_MARKER).unlink(missing_ok=True)
        backfill_points(session)
    assert points() == [5, 10, 40]
