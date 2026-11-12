"""The text a learned rule matches: which part of a booking's description
names the merchant or payee — and so fits the next booking of the same one.
Text in, text out; nothing here reads or writes the database.

Pattern derivation for merchant rules deliberately strips the
transaction-specific noise (trailing order/reference codes) so a rule
generalizes to future variants of the same merchant (e.g.
"AMZN Mktp DE*AB1234" -> pattern "AMZN Mktp DE", matching a future
"AMZN Mktp DE*XY9876" too) while staying a plain substring match — no
regex required, fully explainable. It never strips so much that only a
payment processor or booking type remains ("PAYPAL *NETFLIX.COM" must not
become "PAYPAL", which would rename every future PayPal payment).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from app.db.models import RawTransaction, Transaction

# "*AB1234" — a code containing a digit. "*NETFLIX.COM" (no digit) is the
# actual merchant behind a payment processor and is kept.
_TRAILING_CODE_RE = re.compile(r"\*(?=\S*\d)\S+$")
# A whitespace-separated trailing numeric token of 2+ digits is almost
# always a transaction/order/reference number, not part of the merchant
# name itself (the whitespace requirement avoids stripping something like
# "Store24", where the digits are fused to the name).
_TRAILING_DIGITS_RE = re.compile(r"\s+\d{2,}\s*$")

# Words that say HOW something was paid, not WHO was paid.
_GENERIC_WORDS = {
    "paypal", "sepa", "lastschrift", "kartenzahlung", "karte", "ueberweisung", "überweisung", "gutschrift",
    "dauerauftrag", "visa", "mastercard", "girocard", "debit", "card", "payment", "zahlung", "einkauf",
    "pos", "online", "purchase", "basislastschrift", "folgelastschrift", "sumup", "zettle", "google", "apple",
    "pay", "ref", "eref", "mref", "svwz", "gmbh", "und", "the",
}
MIN_PATTERN_LENGTH = 4


def derive_merchant_pattern(original_description: str) -> str:
    original = original_description.strip()
    text = _TRAILING_CODE_RE.sub("", original)
    text = _TRAILING_DIGITS_RE.sub("", text)
    text = text.strip(" -*#")
    meaningful = [w for w in re.findall(r"[a-zäöüß]+", text.lower()) if len(w) >= 3 and w not in _GENERIC_WORDS]
    if len(text) < MIN_PATTERN_LENGTH or not meaningful:
        # Too little left to identify the merchant -> use the full text,
        # which only matches this very specific description.
        return original
    return text


def raw_extra(raw: RawTransaction | None, key: str) -> str | None:
    if raw is None or not raw.extra_fields_json:
        return None
    try:
        return json.loads(raw.extra_fields_json).get(key)
    except (ValueError, AttributeError):
        return None


def raw_counterparty(raw: RawTransaction | None) -> str | None:
    return raw_extra(raw, "_counterparty")


# --- learning categories -------------------------------------------------------

# Leading words that name the booking type, not the payee:
# "Lastschrift / Belastung REWE Markt GmbH ..." -> "REWE Markt GmbH ...".
_BOOKING_TYPE_WORDS = {
    "lastschrift", "belastung", "gutschrift", "überweisung", "ueberweisung", "sepa", "sepa-lastschrift",
    "sepa-überweisung", "sepa-ueberweisung", "sepa-gutschrift", "dauerauftrag", "kartenzahlung", "kartenumsatz",
    "kartenverfügung", "girocard", "debitkarte", "basislastschrift", "folgelastschrift", "erstlastschrift",
    "echtzeitüberweisung", "echtzeit-überweisung", "onlineüberweisung", "online-überweisung", "abbuchung",
    "einzug", "zahlungseingang", "zahlungsausgang", "übertrag", "uebertrag", "umbuchung", "storno",
    "rücklastschrift", "ruecklastschrift", "an", "von", "bei", "zugunsten", "auftraggeber",
    "empfänger", "empfaenger", "payment", "purchase", "card", "pos",
}
# Where the payee's name ends and booking details begin.
_STOP_WORDS = {
    "vom", "am", "datum", "ref", "ref.", "referenz", "kundenreferenz", "mandatsreferenz", "mandat", "nr", "nr.",
    "nummer", "rechnung", "rechnungsnr", "beleg", "kundennr", "iban", "bic", "iban:", "bic:", "eur", "euro",
    "januar", "februar", "märz", "maerz", "april", "mai", "juni", "juli", "august", "september", "oktober",
    "november", "dezember", "jan", "feb", "mär", "apr", "jun", "jul", "aug", "sep", "sept", "okt", "nov", "dez",
    "january", "february", "march", "may", "june", "july", "october", "december", "oct", "dec",
}
# SEPA field markers, also when printed with a space before the "+" ("EREF + ...").
_SEPA_MARKERS = {"eref", "mref", "kref", "svwz", "abwa", "abwe", "cred", "purp", "bref", "debt", "iban", "bic"}
_STOP_PREFIXES = tuple(f"{marker}+" for marker in _SEPA_MARKERS) + ("end-to-end",)
# Legal forms and fill words: never enough on their own to name a payee
# ("PayPal Europe S.a.r.l. et Cie" must not become a rule for all PayPal payments).
_NON_IDENTIFYING = _GENERIC_WORDS | {
    "europe", "sarl", "cie", "sca", "ltd", "inc", "llc", "kg", "ag", "se", "co", "ohg", "ug", "mbh", "klarna",
    "stripe", "adyen", "einkauf", "kauf", "danke", "vielen", "dank", "ihr", "ihre", "fuer", "für",
    "übertrag", "uebertrag", "umbuchung", "storno",
} | _SEPA_MARKERS
_MAX_PATTERN_WORDS = 5


def _identifying_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zäöüß]+", text.lower()) if len(w) >= 3 and w not in _NON_IDENTIFYING]


@lru_cache(maxsize=65536)  # chain_index asks for every payee text of every booking, on each request that needs it
def derive_category_pattern(text: str) -> str | None:
    """The part of a merchant/description that names WHO was paid, so a
    learned category also fits the next booking with that payee:
    "Lastschrift / Belastung REWE Markt GmbH Einkauf 12,34 EUR vom 01.09."
    -> "REWE Markt GmbH". Booking type, amounts, dates, month names and
    reference codes are left out. The result is always a substring of
    `text` — or None when nothing in it identifies a payee (e.g. a bare
    "PayPal Europe S.a.r.l." line: every PayPal payment looks like that, so
    a rule would give all of them this one category)."""
    original = text.strip()
    tokens = list(re.finditer(r"\S+", original))
    start = 0
    while start < len(tokens):
        word = tokens[start].group().lower().strip(":,")
        if word in _BOOKING_TYPE_WORDS or not re.search(r"\w", word):
            start += 1
        elif start + 1 < len(tokens) and len(tokens[start + 1].group()) == 1 \
                and word + tokens[start + 1].group().lower() in _BOOKING_TYPE_WORDS:
            start += 2  # a booking word broken over two lines: "KARTENVERFÜGUN G"
        else:
            break
    kept = []
    for token in tokens[start:]:
        word = token.group().lower()
        if (any(ch.isdigit() for ch in word) or word.strip(",.;:+") in _STOP_WORDS | _SEPA_MARKERS
                or word.startswith(_STOP_PREFIXES) or word == "+"):
            break
        if kept and word.endswith(":"):
            break  # a field label ("Verwendungszweck:") ends the name
        kept.append(token)
        if len(kept) == _MAX_PATTERN_WORDS:
            break
    while kept and not _identifying_words(kept[-1].group()):
        kept.pop()  # trailing "Einkauf", "GmbH,", "/" ...
    # keep a legal form right after the name ("REWE Markt GmbH")
    if kept:
        following = tokens.index(kept[-1]) + 1
        if following < len(tokens) and len(kept) < _MAX_PATTERN_WORDS \
                and tokens[following].group().lower().strip(",.") in {"gmbh", "ag", "kg", "se", "ug", "ohg", "e.v."}:
            kept.append(tokens[following])
    if not kept:
        return None
    pattern = original[kept[0].start():kept[-1].end()].rstrip(",;:/-")
    if len(pattern) < MIN_PATTERN_LENGTH or not _identifying_words(pattern):
        return None
    return pattern


def category_rule_source(tx: Transaction) -> tuple[str, str]:
    """(match_field, text the pattern is derived from)."""
    if tx.merchant:
        return "merchant", tx.merchant
    return "description", tx.normalized_description or ""
