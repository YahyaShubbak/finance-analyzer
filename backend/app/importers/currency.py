"""Currency code normalization.

Transactions are grouped and formatted by currency code, so "EUR", "eur",
"€" and "Euro" must all end up as the same ISO 4217 code — otherwise one
account silently splits into several "currencies" and the frontend's
number formatter rejects the non-ISO values.
"""
from __future__ import annotations

# Active ISO 4217 codes.
ISO_4217_CODES = frozenset("""
AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD BTN BWP BYN BZD
CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD
GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT
LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR
NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP
STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VES VND VUV WST XAF XCD XOF
XPF YER ZAR ZMW ZWL
""".split())

# Unambiguous symbols/names only. "$" alone is deliberately absent — it is
# used by USD, CAD, AUD, MXN, ... and guessing would mislabel money.
_ALIASES = {
    "€": "EUR", "EURO": "EUR", "EUROS": "EUR",
    "£": "GBP", "GBP£": "GBP",
    "US$": "USD", "USD$": "USD",
    "CA$": "CAD", "C$": "CAD",
    "A$": "AUD", "AU$": "AUD",
    "FR.": "CHF", "SFR": "CHF", "SFR.": "CHF",
    "¥": "JPY", "₹": "INR", "ZŁ": "PLN", "KČ": "CZK",
}


def normalize_currency(raw: str | None) -> str | None:
    """Return the ISO 4217 code for `raw`, or None if it isn't a currency
    this function can identify with certainty."""
    if raw is None:
        return None
    text = str(raw).strip().upper()
    if not text:
        return None
    if text in ISO_4217_CODES:
        return text
    return _ALIASES.get(text)


def is_valid_currency(code: str) -> bool:
    return code in ISO_4217_CODES
