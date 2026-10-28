"""Where a payment took place (app.normalization.location) and the
/api/analytics/by-location report. All texts are invented."""
from __future__ import annotations

import io

import pytest
from sqlmodel import Session, select

from app.db.models import Transaction
from app.normalization.location import LOCATION_VERSION, Location, LocationInput, locate_rows, place_key
from app.services.location_service import refresh_locations


def _card(*texts, **kw):
    return [LocationInput(texts=[t], extra_fields=[kw.get("extra", {})], card_text=t,
                          currency=kw.get("currency", "EUR"), account_currency="EUR") for t in texts]


def _bank(text, extra=None):
    return LocationInput(texts=[text], extra_fields=[extra or {}], currency="EUR", account_currency="EUR")


def test_place_key_ignores_spelling():
    assert place_key("München") == place_key("MUENCHEN") == "MUENCHEN"
    assert place_key("Frankfurt a.M.") == "FRANKFURT A M"
    assert place_key("Málaga") == "MALAGA"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Baeckerei Muster//Bochum/DE 2026-03-04T10:11:12 KFN 1 VJ 2912", Location("DE", "Bochum")),
        ("CAFE EJEMPLO//PALMA/ES 2026-07-01T20:00:00", Location("ES", "Palma")),
        # an unknown town keeps the printed country
        ("BAR EJEMPLO//Pueblo Pequeno/ES 2026-07-02T21:00:00", Location("ES", "Pueblo Pequeno")),
        # without the country code: a domestic payment
        ("KIOSK BEISPIEL//MUENCHEN 2026-03-05T09:00:00", Location("DE", "München")),
        # a web shop paid by card
        ("SHOP.EXAMPLE.DE//0800 1234567/DE 2026-03-06T00:00:00", Location(online=True)),
        # an address, not the card format
        ("Bestellung https://www.example.com/de Kundennummer 123", Location()),
    ],
)
def test_sepa_card_payment_text(text, expected):
    assert locate_rows([_bank(text)]) == [expected]


def test_bank_statements_are_not_read_for_towns():
    # a direct debit names the company's seat, not where you were
    assert locate_rows([_bank("Lastschrift Stadtwerke Bochum Abschlag 03/2026")]) == [Location()]


def test_place_column():
    rows = [
        _bank("Einkauf 1", {"Merchant Area": "Bochum"}),
        _bank("Einkauf 2", {"Ort": "Barcelona"}),
        _bank("Einkauf 3", {"Merchant Area": "shop.example"}),
        _bank("Einkauf 4", {"Merchant Area": "0301234567"}),
        _bank("Einkauf 5", {"Merchant Area": "Beispielstadt"}),
        _bank("Einkauf 6", {"Merchant Area": "St.Gallen"}),
    ]
    assert locate_rows(rows) == [
        Location("DE", "Bochum"), Location("ES", "Barcelona"), Location(online=True),
        Location(), Location(), Location("CH", "St.Gallen"),  # as printed
    ]


def test_town_at_the_end_of_card_texts_when_the_format_prints_it():
    rows = _card(
        "BAECKEREI MUSTER BOCHUM",
        "SUPERMERCADO EJEMPLO 0042 PALMA",
        "RESTAURANTE EJEMPLO PALMA ESP",
        "TANKSTELLE BEISPIEL GMBH DORTMUND",
        "TIENDA EJEMPLO SOLLERIC",          # no known town
        "TEX MEX BEISPIEL BAR",             # neither a town nor a country
    )
    assert locate_rows(rows) == [
        Location("DE", "Bochum"), Location("ES", "Palma"), Location("ES", "Palma"),
        Location("DE", "Dortmund"), Location(), Location(),
    ]


def test_a_format_without_towns_does_not_turn_brands_into_places():
    # only one of five card payments ends in a word that is also a town
    # somewhere: a coincidence in a format that prints no towns
    rows = _card("BEISPIEL SHOP", "MUSTER MARKT", "EXAMPLE STORE", "SAMPLE CAFE", "BRAND PARIS")
    assert locate_rows(rows) == [Location()] * 5


def test_web_shops_and_foreign_currencies():
    rows = _card("NETFLIX.COM", "EXAMPLE.DE MARKETPLACE", "MUSEUM SHOP BEISPIEL", currency="EUR")
    rows[2].currency = "GBP"
    assert locate_rows(rows) == [Location(online=True), Location(online=True), Location("GB")]


# --- through the app -----------------------------------------------------------------------------------


def _account(client, name, account_type):
    r = client.post("/api/accounts", json={"name": name, "account_type": account_type})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _import_csv(client, account_id, content: bytes):
    files = {"file": ("export.csv", io.BytesIO(content), "text/csv")}
    preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id})
    assert preview.status_code == 200, preview.text
    commit = client.post("/api/imports/commit", json={"staging_id": preview.json()["staging_id"], "account_id": account_id})
    assert commit.status_code == 200, commit.text


CARD_CSV = (
    b"Date,Description,Amount\n"
    b"2026-07-01,SUPERMERCADO EJEMPLO PALMA,-40.00\n"
    b"2026-07-02,RESTAURANTE EJEMPLO PALMA ESP,-60.00\n"
    b"2026-07-03,HELADERIA EJEMPLO VALENCIA,-5.50\n"
    b"2026-07-10,BAECKEREI MUSTER BOCHUM,-3.20\n"
    b"2026-07-11,NETFLIX.COM,-12.99\n"
    b"2026-07-12,BEISPIEL VERSAND,-20.00\n"
)


def test_location_report_and_its_transactions(client):
    card = _account(client, "Karte", "credit_card")
    _import_csv(client, card, CARD_CSV)

    rows = client.get("/api/analytics/by-location").json()
    places = {(r["country"], r["city"], r["online"]): (r["amount_minor"], r["transaction_count"]) for r in rows}
    assert places == {
        ("ES", "Palma", False): (10000, 2),
        ("ES", "Valencia", False): (550, 1),
        ("DE", "Bochum", False): (320, 1),
        (None, None, True): (1299, 1),
        (None, None, False): (2000, 1),
    }

    spain = client.get("/api/analytics/by-location/transactions", params={"currency": "EUR", "country": "ES"}).json()
    assert spain["total"] == 3 and spain["amount_minor"] == 10550
    assert {(t["country"], t["city"]) for t in spain["items"]} == {("ES", "Palma"), ("ES", "Valencia")}
    palma = client.get("/api/analytics/by-location/transactions",
                       params={"currency": "EUR", "country": "ES", "city": "Palma"}).json()
    assert palma["total"] == 2
    online = client.get("/api/analytics/by-location/transactions", params={"currency": "EUR", "online": True}).json()
    assert [t["normalized_description"] for t in online["items"]] == ["NETFLIX.COM"]
    unknown = client.get("/api/analytics/by-location/transactions", params={"currency": "EUR"}).json()
    assert [t["normalized_description"] for t in unknown["items"]] == ["BEISPIEL VERSAND"]


def test_outdated_locations_are_worked_out_again(client):
    import app.db.session as db_session

    card = _account(client, "Karte", "credit_card")
    _import_csv(client, card, CARD_CSV)
    with Session(db_session.engine) as session:
        for tx in session.exec(select(Transaction)).all():
            tx.country, tx.city, tx.location_version = None, None, 0
            session.add(tx)
        session.commit()
        assert refresh_locations(session) == 4  # the four transactions with a town
        located = session.exec(select(Transaction).where(Transaction.country == "ES")).all()
        assert len(located) == 3
        assert all(t.location_version == LOCATION_VERSION for t in session.exec(select(Transaction)).all())
        assert refresh_locations(session) == 0


def test_paypal_payments_are_online():
    rows = [_bank("Lastschrift PayPal Europe S.a.r.l. 1234567890 PP.1234.PP Ihr Einkauf bei Beispiel"),
            *_card("PAYPAL *BEISPIELSHOP 4029357733")]
    assert locate_rows(rows) == [Location(online=True), Location(online=True)]
