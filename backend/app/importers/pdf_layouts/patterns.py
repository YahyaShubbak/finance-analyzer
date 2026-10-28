"""Regular expressions and helpers shared by the text-based PDF layout parsers."""
from __future__ import annotations

import re
from datetime import date

from app.importers.parsing_utils import DateParseError, detect_date_format, parse_date, parse_date_flexible

# "15.01.2026", "15/01/26", or "15.01." (German statements often omit the
# year in the table; it is inferred from the statement, see reference_date).
DATE = r"\d{2}[./]\d{2}[./](?:\d{4}|\d{2})?"
_FULL_DATE = re.compile(r"(?<!\d)(\d{2}[./]\d{2}[./](?:\d{4}|\d{2}))(?!\d)")

# An amount always has exactly two decimals in a statement, which is what
# tells it apart from reference numbers: "1.234,56", "1,234.56", "1 234,56",
# "2500.00", "-42,90", "42,90-", "42,90 S", "- 42,90", "€ 12,00".
_NUMBER = r"\d{1,3}(?:[.,']\d{3})+[.,]\d{2}|\d{1,3}(?: \d{3})+[.,]\d{2}|\d+[.,]\d{2}"
_CURRENCY = r"(?:EUR|USD|GBP|CHF|€|\$|£)"
# A trailing "-"/"+" must be attached to the number ("42,90-"); with a
# space in between it belongs to the next number ("+ 100,00 - 50,00").
AMOUNT = (
    rf"(?:{_CURRENCY}\s?)?[-+−–]?\s?(?:{_NUMBER})"
    rf"(?:[-+]|\s?(?:S|H|CR|DR)(?![A-Za-z]))?"
)

_TX_TAIL = (
    rf"(?P<desc>.+?)\s+(?P<amount>{AMOUNT})\s*(?P<currency>{_CURRENCY})?"
    rf"(?:\s+(?P<balance>{AMOUNT})\s*{_CURRENCY}?)?\s*$"
)
TX_LINE_RE = re.compile(rf"^(?P<date>{DATE})\s+(?:(?P<value_date>{DATE})\s+)?{_TX_TAIL}")
# Card statements (e.g. American Express) print "dd.mm dd.mm" — transaction
# and booking date without year and without trailing dot. Only accepted as a
# PAIR, so a single "12.50" at the start of a line is never taken for a date.
_SHORT_PAIR = r"\d{2}\.\d{2}"
TX_LINE_SHORT_RE = re.compile(rf"^(?P<date>{_SHORT_PAIR})\s+(?P<value_date>{_SHORT_PAIR})\s+{_TX_TAIL}")
DATE_PREFIX_RE = re.compile(rf"^(?:{DATE}|{_SHORT_PAIR}\s+{_SHORT_PAIR})\s")


# The value-date line directly below a booking: "02.09.2026 REWE Markt GmbH".
VALUE_DATE_LINE_RE = re.compile(rf"^(?P<date>{DATE})(?:\s+(?P<rest>.*))?$")
# A line that contains an amount (e.g. a sum or another booking's amount)
# is never a continuation of the previous booking.
# A line that ENDS in an amount looks like a booking or a sum of its own
# and is never a continuation; an amount inside purpose text ("Einkauf
# 12,34 EUR am ...") is fine.
AMOUNT_ONLY_RE = re.compile(rf"(?:^|\s)(?:{AMOUNT})\s*(?:{_CURRENCY})?\s*$")
# ... and a line with a SIGNED amount anywhere ("-900,00") is a booking of
# its own (possibly one the parser couldn't read), not purpose text.
# (sign attached to the number, as booking amounts are printed; "- 9.99 %"
# with a space is purpose text).
SIGNED_AMOUNT_RE = re.compile(rf"(?:^|\s)[-+\u2212\u2013](?:{_NUMBER})(?!\d)")
# A line made of dates only (e.g. a statement's period in its header).
DATES_ONLY_RE = re.compile(rf"^(?:{DATE}\s*)+$")


def match_tx_line(line: str):
    """Match a transaction line in any supported date style."""
    return TX_LINE_RE.match(line) or TX_LINE_SHORT_RE.match(line)

PERIOD_RE = re.compile(
    rf"(?:statement period|billing period|abrechnungszeitraum|zeitraum|period|kontoauszug vom|auszug vom)"
    rf"\s*[:\-]?\s*(?:vom\s+)?({DATE})\s*(?:-|–|to|bis)\s*({DATE})",
    re.IGNORECASE,
)
_ANY_DATE_RE = re.compile(rf"(?<![\d.,]){DATE}(?!\d)|^{_SHORT_PAIR}\s+{_SHORT_PAIR}(?=\s)")
_MONEY_RE = re.compile(rf"(?<![\d.,])(?:{_NUMBER})(?!\d)")
_LOWER_WORD_RE = re.compile(r"\b[a-zäöüß][a-zäöüß-]{2,}\b")
_SENTENCE_BREAK_RE = re.compile(r"[a-zäöüß]{2,}[.!?:]\s+[A-ZÄÖÜ]")


def looks_like_prose(text: str) -> bool:
    """A sentence of running text ("bis 31.12.2026 gültig. Nutzen Sie
    das Angebot ..."), not a booking: booking texts are names, upper
    case and abbreviations, with few lower-case words and no sentence break."""
    lower = len(_LOWER_WORD_RE.findall(text))
    return lower >= 6 or (lower >= 3 and bool(_SENTENCE_BREAK_RE.search(text)))


def may_be_missed_booking(line: str) -> bool:
    """A line starting with a date that may be a booking no reader understood
    (warned about, marked in the import review): it holds an amount besides
    its dates, and it isn't a period line or a sentence of running text."""
    if not DATE_PREFIX_RE.match(line) or DATES_ONLY_RE.match(line) or PERIOD_RE.search(line):
        return False
    rest = _ANY_DATE_RE.sub(" ", line)
    return bool(_MONEY_RE.search(rest)) and not looks_like_prose(rest)


# "Kontoauszug Nr. 3/2025 vom 01.03.2025 bis 31.03.2025", "from ... to ..."
_RANGE_RE = re.compile(rf"\b(?:vom|from)\s+({DATE})\s*(?:bis|to|-|–)\s*({DATE})", re.IGNORECASE)

# Lines that state a balance rather than a transaction.
BALANCE_LINE_RE = re.compile(
    r"^(?:(?:alter|neuer|aktueller)\s+kontostand|kontostand|(?:anfangs|end|schluss)saldo|"
    r"saldo(?:\s+(?:vortrag|alt|neu|vom|per))?|(?:opening|closing|previous|new|starting|ending)\s+balance|"
    r"balance\s+(?:brought|carried)\s+forward)\b",
    re.IGNORECASE,
)

# Column headings of statements that print debits and credits in separate
# columns without a sign — the direction is only visible from the column.
_SPLIT_COLUMN_HEADINGS = [
    ("soll", "haben"), ("belastung", "gutschrift"), ("lastschrift", "gutschrift"), ("abgang", "zugang"),
    ("ausgang", "eingang"), ("debit", "credit"), ("withdrawals", "deposits"), ("paid out", "paid in"),
    ("money out", "money in"),
]


def _iso_or_none(text: str) -> str | None:
    try:
        return parse_date_flexible(text).isoformat()
    except DateParseError:
        return None


def parse_period(full_text: str) -> tuple[str | None, str | None]:
    for regex in (PERIOD_RE, _RANGE_RE):
        match = regex.search(full_text)
        if match:
            start, end = _iso_or_none(match.group(1)), _iso_or_none(match.group(2))
            if start and end:
                return start, end
    return None, None


def reference_date(full_text: str, period_end: str | None) -> date | None:
    """The date that yearless "15.01." dates are completed against: the end
    of the statement period, else the latest full date printed anywhere in
    the document. Never today's date — that would put an old statement
    into the wrong year."""
    if period_end:
        return date.fromisoformat(period_end)
    texts = _FULL_DATE.findall(full_text)
    if not texts:
        return None
    # One format for the whole document ("05/09/26" alone is ambiguous).
    fmt, _candidates = detect_date_format(texts)
    found = []
    for text in texts:
        try:
            found.append(parse_date(text, fmt) if fmt else parse_date_flexible(text))
        except DateParseError:
            continue
    return max(found) if found else None


def complete_date(date_text: str, reference: date | None) -> str:
    """Add the year to a "15.01." style date: the reference year, or the
    year before for months after the reference month (a December line on a
    statement ending in January). Without a reference the text is returned
    unchanged, so it fails to parse and is reported."""
    if not re.fullmatch(r"\d{2}[./]\d{2}[./]?", date_text) or reference is None:
        return date_text
    month = int(date_text[3:5])
    year = reference.year - 1 if month > reference.month else reference.year
    separator = "" if date_text[-1] in "./" else date_text[2]
    return f"{date_text}{separator}{year}"


def header_zone(full_text: str, lines: int = 40) -> str:
    """The document's non-transaction text near the top, where titles like
    "Kreditkartenabrechnung" appear. Transaction lines are left out: a bank
    statement line such as "Kreditkartenabrechnung VISA -312,40" is the
    card being paid, not the document's title."""
    non_tx = [line for line in full_text.splitlines() if line.strip() and not match_tx_line(line.strip())]
    return "\n".join(non_tx[:lines]).lower()


def card_title_in_parts(top: str) -> bool:
    """A card statement whose title is split over separate words/lines
    ("American Express ... Abrechnung", "Ihre Kreditkarte ... Abrechnung vom")
    — but never a document that calls itself an account statement."""
    if "kontoauszug" in top or "account statement" in top or "girokonto" in top:
        return False
    card = "kreditkarte" in top or "credit card" in top or "american express" in top or "amex" in top
    statement = "abrechnung" in top or "statement" in top or "rechnungsbetrag" in top
    return card and statement


def has_split_debit_credit_columns(full_text: str) -> bool:
    """True when a (non-transaction) line holds both a debit and a credit
    column heading, e.g. "Datum  Buchungstext  Soll  Haben"."""
    for line in full_text.splitlines():
        lowered = f" {line.strip().lower()} "
        if not lowered.strip() or match_tx_line(line.strip()):
            continue
        for debit, credit in _SPLIT_COLUMN_HEADINGS:
            if re.search(rf"\b{debit}\b", lowered) and re.search(rf"\b{credit}\b", lowered):
                return True
    return False


def amount_has_sign(amount_text: str) -> bool:
    text = amount_text.strip()
    return bool(re.search(r"^[^\d]*[-+−–]|[-+]$|(?:S|H|CR|DR)$", text))
