"""Mapping arbitrary spreadsheet/CSV headers to logical transaction fields.

We never silently guess when the data is ambiguous — if a required field
can't be confidently identified, the import is flagged ambiguous and the
user maps the columns in the import dialog instead.

Matching works on a normalized form of each header (lowercase, umlauts
transliterated, whitespace collapsed) in three tiers, each only considering
headers not already claimed by a more important field:

1. exact match against a field's candidate names;
2. exact match after dropping a parenthesized suffix, so "Betrag (€)" and
   "Amount (EUR)" match "betrag"/"amount";
3. whole-word match — every word of a multi-word candidate must appear as
   a word in the header ("booking date utc" matches "booking date").
   Single, generic words ("name", "value", "text", ...) are exact-only,
   which is what stops e.g. "Value Date" from being read as the amount.

Known bank export formats (BANK_FORMATS) are recognized by their header
signature and get a fixed mapping on top of the generic detection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.i18n import tr

# Field -> candidate names in priority order (earlier = preferred).
_CANDIDATES: dict[str, list[str]] = {
    "date": [
        "buchungstag", "buchungsdatum", "buchung", "booking date", "book date", "transaction date",
        "posting date", "started date", "completed date", "date", "datum",
    ],
    "value_date": [
        "valutadatum", "valuta", "wertstellung", "wertstellungsdatum", "wertstellung valuta", "value date",
    ],
    "amount": [
        "betrag", "amount", "umsatz", "umsatz in eur", "betrag eur", "value",
    ],
    # A separate "S"/"H" (Soll/Haben) column next to an unsigned amount
    # (Volksbank/VR format), see tabular._sign_indicator_column.
    "sign_indicator": ["soll/haben", "soll haben", "haben/soll", "s/h", "h/s", "kennung", "soll/haben kennung",
                       "debit/credit", "credit/debit", "dr/cr", "cr/dr"],
    "debit": ["soll", "debit", "withdrawal", "withdrawals", "ausgang", "belastung", "money out", "paid out"],
    "credit": ["haben", "credit", "deposit", "deposits", "eingang", "gutschrift", "money in", "paid in"],
    "currency": ["waehrung", "currency", "ccy", "wahrung"],
    # The card network's merchant category ("GROCERY STORES/SUPERMARKETS"),
    # used to categorize when no rule names the merchant.
    "merchant_category": ["merchant category", "mcc", "mcc description", "haendlerkategorie", "haendler kategorie",
                          "branche"],
    "counterparty_iban": [
        "kontonummer iban", "kontonummer/iban", "iban zahlungsbeteiligter", "partner iban",
        "gegenkonto", "counterparty iban", "iban",
    ],
    # DKB-style separate columns; the counterparty is the payee for money
    # out and the payer for money in (see tabular._counterparty).
    "payee": ["zahlungsempfaenger*in", "zahlungsempfaenger", "empfaenger", "payee", "recipient", "merchant"],
    "payer": ["zahlungspflichtige*r", "zahlungspflichtiger", "auftraggeber", "payer"],
    "counterparty": [
        "beguenstigter/zahlungspflichtiger", "auftraggeber/empfaenger", "auftraggeber / empfaenger",
        "auftraggeber/zahlungsempfaenger",
        "auftraggeber/beguenstigter", "name zahlungsbeteiligter", "zahlungsbeteiligter", "partner name",
        "counterparty", "gegenpartei", "name",
    ],
    "description": [
        "verwendungszweck", "payment reference", "reference", "description", "details", "memo",
        "buchungsdetails", "beschreibung", "narrative", "text",
    ],
    "booking_text": ["buchungstext", "umsatztyp", "umsatzart", "vorgang", "transaction type", "type"],
    # Booked vs. pending ("Vorgemerkt", "PENDING", "REVERTED").
    "status": ["status", "state", "umsatzstatus", "buchungsstatus"],
    # Separate fee column; only used where the bank format says the fee is
    # NOT included in the amount (BankFormat.fee_separate).
    "fee": ["fee"],
}

# Assignment order: amount-related fields first so e.g. "Umsatz" can't be
# claimed as a description; description-like fields last.
FIELD_ORDER = [
    "date", "value_date", "amount", "sign_indicator", "debit", "credit", "currency", "counterparty_iban",
    "merchant_category", "payee", "payer", "counterparty", "description", "booking_text", "status", "fee",
]
LOGICAL_FIELDS = tuple(FIELD_ORDER)

# Candidates too generic for word-level matching.
_EXACT_ONLY = {"name", "value", "text", "type", "reference", "date", "datum", "details", "memo", "buchung",
               "umsatz", "soll", "haben", "iban", "credit", "debit", "status", "state", "fee", "s/h", "h/s",
               "kennung", "dr/cr", "cr/dr"}

# Headers that look amount-/currency-like but must never be used as such:
# balances, fees, exchange rates, and the ORIGINAL (foreign) amount/currency
# of card payments abroad ("Betrag in Fremdwährung", "Original Currency").
_NEVER_AMOUNT = re.compile(
    r"saldo|balance|kontostand|urspr|original|auslagenersatz|fee|gebuehr|kurs|rate|fremd|foreign"
)
_NEVER_CURRENCY = re.compile(r"original|urspr|fremd|foreign|exchange|kurs|rate")
# A column with the amount in another currency ("Currency Amount", "Betrag in
# Fremdwährung") means a plain "Currency" column describes THAT amount, not
# the booked one — the account's currency applies instead.
_FOREIGN_AMOUNT_COLUMN = re.compile(r"(?:currency|waehrung) (?:amount|betrag)|fremdwaehrung|original amount|foreign amount")
# Where, or what kind of business, but never who: "Merchant Area" is the
# merchant's town, "Merchant Category" the card network's category.
_NEVER_PARTY = re.compile(r"\b(?:area|category|kategorie|city|stadt|ort|country|land|location|mcc|branche)\b")


def normalize_header(h: str) -> str:
    h = (h or "").replace("﻿", "").strip().strip('"')
    h = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", h).lower()  # "TransactionDate" -> "transaction date"
    for src, dst in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        h = h.replace(src, dst)
    h = re.sub(r"[_\-]+", " ", h)
    h = re.sub(r"\s+", " ", h)
    return h.strip()


def _core(norm: str) -> str:
    return re.sub(r"\s*\(.*?\)\s*", " ", norm).strip()


def _words(norm: str) -> set[str]:
    return set(re.findall(r"[a-z0-9*]+", norm))


def _matches(norm: str, candidate: str, tier: int) -> bool:
    if tier == 1:
        # spacing differs between exports: "BuchungsDatum", "Transaction Date"
        return norm == candidate or norm.replace(" ", "") == candidate.replace(" ", "")
    if tier == 2:
        return _core(norm) == candidate
    if candidate in _EXACT_ONLY:
        return False
    cand_words = _words(candidate)
    return bool(cand_words) and cand_words <= _words(norm)


@dataclass(frozen=True)
class BankFormat:
    name: str
    signature: frozenset[str]          # normalized headers that must all be present
    mapping: dict[str, str] = field(default_factory=dict)  # field -> normalized header
    date_format: str | None = None
    decimal_separator: str | None = None
    fee_separate: bool = False  # amount excludes the fee column (Revolut)


# Header layouts of common German bank exports. Matched by signature, so a
# bank changing its format simply falls back to generic detection.
BANK_FORMATS: list[BankFormat] = [
    BankFormat(
        name="Sparkasse (CSV-CAMT)",
        signature=frozenset({"auftragskonto", "buchungstag", "valutadatum", "buchungstext",
                             "verwendungszweck", "beguenstigter/zahlungspflichtiger", "betrag"}),
        mapping={"date": "buchungstag", "value_date": "valutadatum", "description": "verwendungszweck",
                 "counterparty": "beguenstigter/zahlungspflichtiger", "booking_text": "buchungstext",
                 "counterparty_iban": "kontonummer/iban", "amount": "betrag", "currency": "waehrung"},
        decimal_separator=",",
    ),
    BankFormat(
        name="DKB",
        signature=frozenset({"buchungsdatum", "zahlungspflichtige*r", "zahlungsempfaenger*in", "verwendungszweck"}),
        mapping={"date": "buchungsdatum", "value_date": "wertstellung", "payer": "zahlungspflichtige*r",
                 "payee": "zahlungsempfaenger*in", "description": "verwendungszweck", "booking_text": "umsatztyp",
                 "counterparty_iban": "iban"},
        decimal_separator=",",
    ),
    BankFormat(
        name="ING",
        signature=frozenset({"buchung", "auftraggeber/empfaenger", "verwendungszweck", "betrag"}),
        mapping={"date": "buchung", "value_date": "wertstellungsdatum", "counterparty": "auftraggeber/empfaenger",
                 "description": "verwendungszweck", "booking_text": "buchungstext", "amount": "betrag"},
        decimal_separator=",",
    ),
    BankFormat(
        name="comdirect",
        signature=frozenset({"buchungstag", "vorgang", "buchungstext", "umsatz in eur"}),
        mapping={"date": "buchungstag", "description": "buchungstext", "booking_text": "vorgang",
                 "amount": "umsatz in eur"},
        decimal_separator=",",
    ),
    BankFormat(
        name="Commerzbank",
        signature=frozenset({"buchungstag", "wertstellung", "umsatzart", "buchungstext", "betrag", "iban kontoinhaber"}),
        mapping={"date": "buchungstag", "value_date": "wertstellung", "description": "buchungstext",
                 "booking_text": "umsatzart", "amount": "betrag", "currency": "waehrung"},
        decimal_separator=",",
    ),
    BankFormat(
        name="Revolut",
        signature=frozenset({"type", "started date", "completed date", "description", "amount", "fee", "state"}),
        mapping={"date": "completed date", "description": "description", "amount": "amount", "fee": "fee",
                 "currency": "currency", "status": "state", "booking_text": "type"},
        decimal_separator=".",
        fee_separate=True,
    ),
    # Card account export with English headers and the card network's
    # merchant category. Booking date, as in the issuer's PDF statement, so
    # both describe a purchase with the same date.
    BankFormat(
        name="Card export with merchant category",
        signature=frozenset({"transaction date", "text", "type", "currency amount", "amount", "merchant category",
                             "book date", "value date"}),
        mapping={"date": "book date", "value_date": "value date", "description": "text", "booking_text": "type",
                 "amount": "amount", "merchant_category": "merchant category"},
        decimal_separator=".",
    ),
    BankFormat(
        name="N26",
        signature=frozenset({"booking date", "partner name", "payment reference"}),
        mapping={"date": "booking date", "value_date": "value date", "counterparty": "partner name",
                 "counterparty_iban": "partner iban", "description": "payment reference", "booking_text": "type"},
        date_format="%Y-%m-%d",
        decimal_separator=".",
    ),
]


def layout_label(name: str | None) -> str | None:
    """Display name of a detected format in the UI's language (bank names stay as they are)."""
    if name == "Card export with merchant category":
        return tr("Card export with merchant category")
    return name


def detect_bank_format(headers: list[str]) -> BankFormat | None:
    normalized = {normalize_header(h) for h in headers}
    for fmt in BANK_FORMATS:
        if fmt.signature <= normalized:
            return fmt
    return None


def detect_columns(headers: list[str]) -> dict[str, str | None]:
    """Return a mapping of logical field name -> actual header name (or None)."""
    normalized = [(h, normalize_header(h)) for h in headers if h and h.strip()]
    result: dict[str, str | None] = {f: None for f in FIELD_ORDER}
    claimed: set[str] = set()

    bank_format = detect_bank_format(headers)
    if bank_format is not None:
        for logical_field, norm_name in bank_format.mapping.items():
            header = next((h for h, n in normalized if n == norm_name and h not in claimed), None)
            if header is not None:
                result[logical_field] = header
                claimed.add(header)

    for logical_field in FIELD_ORDER:
        if result[logical_field] is not None:
            continue
        found = None
        for tier in (1, 2, 3):
            for candidate in _CANDIDATES[logical_field]:
                for header, norm in normalized:
                    if header in claimed:
                        continue
                    if logical_field == "amount" and _NEVER_AMOUNT.search(norm):
                        continue
                    if logical_field == "currency" and _NEVER_CURRENCY.search(norm):
                        continue
                    if logical_field in ("payee", "payer") and "/" in norm:
                        continue  # "Auftraggeber/Zahlungsempfänger" names both sides: a counterparty column
                    if logical_field in ("payee", "payer", "counterparty") and _NEVER_PARTY.search(norm):
                        continue
                    if _matches(norm, candidate, tier):
                        found = header
                        break
                if found:
                    break
            if found:
                break
        if found is not None:
            result[logical_field] = found
            claimed.add(found)

    if result["currency"] and any(_FOREIGN_AMOUNT_COLUMN.search(n) for _h, n in normalized):
        result["currency"] = None

    # A generic "Name" column together with separate payer/payee columns
    # is ambiguous; prefer the explicit ones.
    if result["payee"] or result["payer"]:
        if result["counterparty"] and normalize_header(result["counterparty"]) == "name":
            result["counterparty"] = None

    return result


def mapping_is_ambiguous(mapping: dict[str, str | None]) -> bool:
    """An import is ambiguous unless we have a date, some text to describe
    the transaction, and either a single amount column or a debit/credit
    pair."""
    if not mapping.get("date"):
        return True
    if not any(mapping.get(f) for f in ("description", "counterparty", "payee", "payer", "booking_text")):
        return True
    return not (mapping.get("amount") or mapping.get("debit") or mapping.get("credit"))


def header_score(headers: list[str]) -> int:
    """How much a row looks like a header row: number of logical fields it
    maps, or 0 when essential fields are missing."""
    mapping = detect_columns(headers)
    if mapping_is_ambiguous(mapping):
        return 0
    return sum(1 for v in mapping.values() if v)


def detect_header_row(rows: list[list[str]], max_scan: int = 30) -> int | None:
    """Index of the header row. Many bank exports (DKB, ING, comdirect)
    start with a few lines of account metadata before the actual table."""
    best_index, best_score = None, 0
    for index, row in enumerate(rows[:max_scan]):
        cells = [str(c) if c is not None else "" for c in row]
        if sum(1 for c in cells if c.strip()) < 3:
            continue
        score = header_score(cells)
        if score > best_score:
            best_index, best_score = index, score
    return best_index
