"""Where a payment took place, country and town, as far as the statement says.

Only what a statement actually prints is used, most explicit first:

1. "MERCHANT//TOWN/DE": the SEPA card-payment format German banks print for
   girocard and debit-card payments. Gives the country code and the town.
   A web address in a card payment's merchant text ("SHOP.DE"), or a
   payment through PayPal, makes it an online purchase, whatever seat the
   statement prints.
2. A place column of the export ("Merchant Area", "Ort", "City", ...): a
   town; a web address there means an online purchase.
3. The end of a card payment's merchant text ("MERCADONA PALMA" or
   "... PALMA ESP"), which is where card networks put the merchant's town —
   on credit-card statements whose format does that (see locate_rows). Bank
   statements are not read this way: a direct debit's "Stadtwerke Bochum"
   names the company, not a place you were.
4. A foreign currency only one country uses (GBP for Great Britain, CHF for
   Switzerland, ...).

A town is recognized by the GeoNames index in places.tsv.gz (towns with
15,000 or more inhabitants, CC BY 4.0, geonames.org; rebuilt by
scripts/build_places.py). Nothing is guessed: no town, no country. Bank
transfers and direct debits normally carry no place at all.
"""
from __future__ import annotations

import gzip
import re
import unicodedata
from dataclasses import dataclass
from functools import cache
from pathlib import Path

#: Bump when the rules below change, so stored locations are worked out again.
LOCATION_VERSION = 3

PLACES_FILE = Path(__file__).with_name("places.tsv.gz")


@dataclass(frozen=True)
class Location:
    country: str | None = None  # ISO 3166-1 alpha-2
    city: str | None = None
    online: bool = False


NO_LOCATION = Location()

_TRANSLITERATE = str.maketrans({"Ä": "AE", "Ö": "OE", "Ü": "UE", "ß": "SS", "ẞ": "SS"})


def place_key(text: str) -> str:
    """A spelling-insensitive key for a place name: upper case, umlauts
    written out (München -> MUENCHEN), other accents dropped, punctuation
    to single spaces."""
    upper = text.upper().translate(_TRANSLITERATE)
    plain = unicodedata.normalize("NFKD", upper).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", plain).split())


@dataclass(frozen=True)
class _Town:
    country: str
    name: str


@cache
def _places() -> dict[str, _Town]:
    index: dict[str, _Town] = {}
    with gzip.open(PLACES_FILE, "rt", encoding="utf-8") as f:
        for line in f:
            country, name, *keys = line.rstrip("\n").split("\t")
            town = _Town(country, name)
            for key in keys:
                index.setdefault(key, town)
            # Statements written without umlauts drop the dots too ("MUNCHEN").
            folded = place_key(unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode())
            index.setdefault(folded, town)
    return index


# Words at the end of a merchant text that are a place name somewhere in the
# world but on a statement mean something else.
_NOT_A_TOWN = frozenset("""
    AG BANK BAR BEACH BERG BURG CAFE CARD CASH CENTER CENTRE CITY CLUB DEUTSCHLAND
    DIENST DIREKT DORF EUROPE FILIALE FOOD GERMANY GMBH GROUP HAUS HOF HOTEL
    INTERNATIONAL KG KIOSK LAND MARKET MARKT MITTE MOBILE NORD NORTH OST ONLINE
    PARK PAY PLATZ PLAZA POST PRIME SHOP SQUARE STATION STORE SUED SOUTH TAXI
    TICKET TOWER TRAVEL WEST WORLD ZENTRUM
""".split())

# Card networks put the country after the town, as ISO alpha-2 or alpha-3.
_ALPHA3 = {
    "DEU": "DE", "ESP": "ES", "FRA": "FR", "ITA": "IT", "AUT": "AT", "CHE": "CH", "NLD": "NL", "BEL": "BE",
    "LUX": "LU", "DNK": "DK", "SWE": "SE", "NOR": "NO", "FIN": "FI", "POL": "PL", "CZE": "CZ", "HUN": "HU",
    "PRT": "PT", "GRC": "GR", "HRV": "HR", "SVN": "SI", "SVK": "SK", "IRL": "IE", "GBR": "GB", "USA": "US",
    "TUR": "TR", "ROU": "RO", "BGR": "BG", "EST": "EE", "LVA": "LV", "LTU": "LT", "MLT": "MT", "CYP": "CY",
    "ISL": "IS", "MAR": "MA", "EGY": "EG", "THA": "TH", "JPN": "JP", "CAN": "CA", "AUS": "AU", "MEX": "MX",
    "ARE": "AE", "TUN": "TN",
}
# Codes that are also words ("BAR DEL MAR", "TEX MEX", "... AUS") or airports (FRA): they only
# count after a town of that country.
_ALPHA3_NEEDS_TOWN = frozenset({"MAR", "MEX", "CAN", "ARE", "TUN", "EST", "AUS", "FRA", "ISL", "EGY", "NOR"})
# Currencies used by exactly one country (the euro and the dollar are not).
_CURRENCY_COUNTRY = {
    "GBP": "GB", "CHF": "CH", "SEK": "SE", "NOK": "NO", "DKK": "DK", "PLN": "PL", "CZK": "CZ", "HUF": "HU",
    "RON": "RO", "BGN": "BG", "ISK": "IS", "TRY": "TR", "JPY": "JP", "CNY": "CN", "THB": "TH", "INR": "IN",
    "MAD": "MA", "EGP": "EG", "AED": "AE", "MXN": "MX", "CAD": "CA", "AUD": "AU", "NZD": "NZ", "ZAR": "ZA",
    "BRL": "BR", "KRW": "KR", "SGD": "SG", "HKD": "HK", "IDR": "ID", "VND": "VN", "PHP": "PH", "MYR": "MY",
    "ILS": "IL", "RSD": "RS", "UAH": "UA", "GEL": "GE", "ALL": "AL", "MKD": "MK", "BAM": "BA", "TND": "TN",
}

_SEPA_CARD_RE = re.compile(r"(?<![:/])//\s*([^/]{2,40}?)\s*(?:/\s*([A-Z]{2})\b|(?=\s+\d{4}-\d{2}-\d{2})|$)")
_URL_RE = re.compile(r"^(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)*\.[a-z]{2,10}(?:/\S*)?$", re.IGNORECASE)
# "NETFLIX.COM", "shop.example.de/order": a web shop
_WEB_ADDRESS_RE = re.compile(r"\b[\w-]{2,}\.(?:com|de|net|org|eu|io|co\.uk|uk|fr|es|it|nl|at|ch|app|shop|store)\b", re.IGNORECASE)
_PAYPAL_RE = re.compile(r"\bpaypal\b|\bpp\.\d", re.IGNORECASE)
_PHONE_RE = re.compile(r"^\+?[\d ()/.-]{6,}$")
_PLACE_COLUMN_RE = re.compile(
    r"^(?:merchant ?(?:area|city|location|town|ort)|(?:händler|haendler)(?:ort|stadt)|ort|stadt|city|town|location|standort|place)$",
    re.IGNORECASE,
)
# Trailing noise after a card payment's town: store numbers, terminal ids, legal forms.
_LEGAL_FORMS = frozenset("GMBH MBH CO KG AG SE UG OHG EK E K KGAA LTD SL SA SRL BV INC LLC SAS SARL SPA".split())


def _display_name(town: _Town, printed: str) -> str:
    """The index's name when the statement printed that name ("MUENCHEN" ->
    "München"); otherwise the name as printed — the town's own language
    rather than the index's English ("ROMA" -> "Roma", not "Rome")."""
    key = place_key(printed)
    folded = place_key(unicodedata.normalize("NFKD", town.name).encode("ascii", "ignore").decode())
    if key in (place_key(town.name), folded):
        return town.name
    printed = " ".join(printed.split())
    if printed.isupper() or printed.islower():
        printed = re.sub(r"[^\W\d_]+", lambda m: m.group(0).capitalize(), printed.lower())
    return printed or town.name


def _lookup(name: str, country: str | None = None) -> _Town | None:
    key = place_key(name)
    if not key or key in _NOT_A_TOWN or len(key) < 3:
        return None
    town = _places().get(key)
    if town is None or (country and town.country != country):
        return None
    return town


def _from_sepa_card_text(text: str) -> Location | None:
    """"MERCHANT//TOWN/CC 2025-03-04T12:00:00 KFN ..." (CC may be missing)."""
    m = _SEPA_CARD_RE.search(text)
    if not m:
        return None
    raw_town, country = m.group(1).strip(), m.group(2)
    merchant = text[max(0, m.start() - 40):m.start()]
    if _WEB_ADDRESS_RE.search(merchant) or _URL_RE.match(raw_town) or _PHONE_RE.match(raw_town):
        return Location(online=True)  # "SHOP.DE//0800 123456/DE": a web shop, no town
    # without a country code the bank printed a domestic payment
    town = _lookup(raw_town, country or "DE")
    if town:
        return Location(country=town.country, city=_display_name(town, raw_town))
    if country:
        return Location(country=country, city=_title(raw_town))
    return None


def _title(raw: str) -> str | None:
    words = place_key(raw).split()
    return " ".join(w.capitalize() for w in words) or None


def _from_place_column(value: str) -> Location | None:
    value = value.strip()
    if not value:
        return None
    town = _lookup(value)  # first: "St.Gallen" is a town, not a web address
    if town:
        return Location(country=town.country, city=_display_name(town, value))
    if _URL_RE.match(value):
        return Location(online=True)
    return None  # a phone number (ordered by phone or online) or an unknown name: place unknown


def _from_merchant_text(text: str) -> Location | None:
    """The town at the end of a card payment's merchant text, optionally
    followed by the country code ("BAECKEREI MUSTER BOCHUM", "MERCADONA PALMA ESP")."""
    words = place_key(text).split()
    country = None
    while words and (any(c.isdigit() for c in words[-1]) or words[-1] in _LEGAL_FORMS):
        words.pop()
    code = None
    if len(words) >= 2 and words[-1] in _ALPHA3:
        code = words.pop()
        country = _ALPHA3[code]
    elif len(words) >= 3 and len(words[-1]) == 2 and words[-1].isalpha():
        # "... PALMA ES": a two-letter code only counts with a town of that country before it
        country = words[-1]
        candidate = _town_at_end(words[:-1], country)
        if candidate:
            return candidate
        country = None
    found = _town_at_end(words, country)
    if found:
        return found
    if country and words and code not in _ALPHA3_NEEDS_TOWN:
        return Location(country=country)
    return None


def _town_at_end(words: list[str], country: str | None) -> Location | None:
    # the merchant's name comes first, so at least one word must remain before the town
    for size in (3, 2, 1):
        if len(words) <= size:
            continue
        printed = " ".join(words[-size:])
        town = _lookup(printed, country)
        if town:
            return Location(country=town.country, city=_display_name(town, printed))
    return None


@dataclass
class LocationInput:
    """What one transaction tells about its place."""

    texts: list[str | None]  # description and detail lines
    extra_fields: list[dict]  # extra columns of its source rows (its own, and rows merged into it)
    card_text: str | None = None  # merchant text of a card payment on a card account
    currency: str | None = None
    account_currency: str | None = None


def locate_rows(rows: list[LocationInput]) -> list[Location]:
    """Locations for the transactions of ONE file. A town at the end of a
    card payment's merchant text only counts when the file's format puts
    the town there: when at least half of its card payments end in a
    known town. Otherwise those matches are coincidences (a brand that
    shares its name with a town) and are ignored."""
    tails = [_from_merchant_text(r.card_text) if r.card_text else None for r in rows]
    card_rows = sum(1 for r in rows if r.card_text)
    with_town = sum(1 for t in tails if t and t.city)
    towns_printed = with_town >= 3 and with_town * 2 >= card_rows
    result = []
    for row, tail in zip(rows, tails, strict=True):
        found = _from_sepa_card_text(" ".join(t for t in row.texts if t))
        if found is None and row.card_text and _WEB_ADDRESS_RE.search(row.card_text):
            found = Location(online=True)  # a web shop, wherever its seat is printed
        if found is None and any(t and _PAYPAL_RE.search(t) for t in row.texts):
            found = Location(online=True)  # paid through PayPal: bought online
        found = found or _from_place_column_of(row) or (tail if towns_printed else None)
        if found is None:
            country = _foreign_currency(row.currency, row.account_currency, row.extra_fields)
            found = Location(country=country) if country else NO_LOCATION
        result.append(found)
    return result


def _from_place_column_of(row: LocationInput) -> Location | None:
    for extra in row.extra_fields:
        for column, value in extra.items():
            if isinstance(value, str) and _PLACE_COLUMN_RE.match(column.strip()):
                found = _from_place_column(value)
                if found:
                    return found
    return None


def _foreign_currency(currency: str | None, account_currency: str | None, extra_fields: list[dict]) -> str | None:
    candidates = [currency] + [
        v for extra in extra_fields for k, v in extra.items()
        if isinstance(v, str) and re.fullmatch(r"(?:original |foreign |fremd)?(?:currency|waehrung|währung)", k.strip(), re.IGNORECASE)
    ]
    for code in candidates:
        code = (code or "").strip().upper()
        if code and code != (account_currency or "").upper() and code in _CURRENCY_COUNTRY:
            return _CURRENCY_COUNTRY[code]
    return None
