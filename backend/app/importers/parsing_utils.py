"""Robust, dependency-light parsing helpers for amounts and dates.

Money is always converted to integer minor units via Decimal — never via
float — to avoid rounding errors.

Two properties matter more than cleverness here:

* **Consistency within a file.** Whether "1.500" means 1500 or 1.5, and
  whether "02/03/2026" is the 2nd of March or the 3rd of February, can't
  be decided from one value. `detect_decimal_separator` and
  `detect_date_format` look at *all* values of a column and pick the one
  interpretation that fits every row; the per-value parsers then apply it.
* **Never silently guess.** When a value is genuinely ambiguous and no
  file-level decision is available, parsing raises instead of picking an
  interpretation that may be off by a factor of 1000.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.i18n import tr

# Characters banks use as a minus sign: ASCII hyphen-minus, Unicode minus,
# en dash (seen in PDF exports) and the small/full-width hyphen-minus.
_MINUS_TRANSLATION = str.maketrans({"\u2212": "-", "\u2013": "-", "\ufe63": "-", "\uff0d": "-",
                                    "\u2010": "-", "\u2011": "-",
                                    "\u00a0": " ", "\u2007": " ", "\u2009": " ", "\u202f": " ",
                                    "'": ""})  # Swiss "1'234.50" grouping
_NUMERIC_CORE = re.compile(r"\d(?:.*\d)?")
_CURRENCY_TOKEN = r"(?:[A-Z]{3}|[A-Za-z]{0,2}[€$£¥₹]|Euro|EURO|euro|Fr\.|SFr\.|kr|Kr|zł)"  # noqa: S105 — not a password
# Sign markers after the number: "42,90-", "42,90 S" (Soll = debit),
# "42,90 H" (Haben = credit), "42.90 DR" / "42.90 CR".
_NEGATIVE_MARKERS = {"-", "S", "DR", "Dr", "Soll"}
_POSITIVE_MARKERS = {"", "+", "H", "CR", "Cr", "Haben"}
_NUMBER_BODY = re.compile(r"^\d[\d.,]*$")

DECIMAL_COMMA = ","
DECIMAL_POINT = "."

_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d.%m.%y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d/%m/%y",
    "%m/%d/%y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%d-%b-%Y",
    "%Y%m%d",
]
DATE_FORMATS = tuple(_DATE_FORMATS)


class AmountParseError(ValueError):
    pass


class AmbiguousAmountError(AmountParseError):
    """The value could be read with either decimal separator ("1,234"
    or "1.500"), and no file-level separator was supplied."""


class DateParseError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Amounts
# ---------------------------------------------------------------------------

_LETTER_MARKERS = {"S", "DR", "Dr", "Soll", "H", "CR", "Cr", "Haben"}
_SPACE_GROUPED = re.compile(r"^\d{1,3}(?: \d{3})+(?:[.,]\d+)?$")


def _split_sign(raw: str) -> tuple[bool, str, bool]:
    """Strip currency and every sign notation, returning
    (is_negative, bare number text, has_letter_marker). The bare text is
    left unvalidated; anything unexpected (including contradicting signs
    such as "-12,00 H") makes it fail _NUMBER_BODY later."""
    text = raw.strip().translate(_MINUS_TRANSLATION)
    parenthesized = False
    if text.startswith("(") and text.endswith(")"):
        parenthesized = True
        text = text[1:-1].strip()

    core_match = _NUMERIC_CORE.search(text)
    if not core_match:
        return parenthesized, "", False
    core = core_match.group(0)
    if " " in core:
        # Only real digit grouping ("1 234,56"), never "12 34".
        if not _SPACE_GROUPED.match(core):
            return parenthesized, "?", False
        core = core.replace(" ", "")
    prefix, suffix = text[:core_match.start()], text[core_match.end():]

    prefix = re.sub(_CURRENCY_TOKEN, "", prefix).replace(" ", "")
    if prefix not in ("", "+", "-"):
        return parenthesized, "?", False

    suffix = suffix.strip()
    suffix = re.sub(r"^" + _CURRENCY_TOKEN + r"\s*", "", suffix)
    suffix = re.sub(r"\s*" + _CURRENCY_TOKEN + r"$", "", suffix).strip()
    if suffix not in _NEGATIVE_MARKERS and suffix not in _POSITIVE_MARKERS:
        return parenthesized, "?", False

    signs = []  # every sign notation present, as True = negative
    if parenthesized:
        signs.append(True)
    if prefix:
        signs.append(prefix == "-")
    if suffix:
        signs.append(suffix in _NEGATIVE_MARKERS)
    if len(set(signs)) > 1:
        return False, "?", False  # "-12,00 H", "+12,00 S", "(12,00) CR": contradictory
    return bool(signs and signs[0]), core, suffix in _LETTER_MARKERS


def has_debit_credit_marker(raw: str) -> bool:
    """True when the amount carries an explicit Soll/Haben or DR/CR marker
    ("45,00 S", "300.00 CR"). Such a marker states the direction from the
    account holder's point of view and must not be inverted by any
    statement-specific sign convention."""
    return _split_sign(str(raw))[2]


def _fraction_digits(text: str, separator: str) -> int | None:
    idx = text.rfind(separator)
    return None if idx == -1 else len(text) - idx - 1


def detect_decimal_separator(values: list[str]) -> str | None:
    """Look at all amount strings of one file and decide which character is
    the decimal separator. Returns "," or ".", or None when the values give
    no evidence (all whole numbers) or contradict each other."""
    votes = {DECIMAL_COMMA: 0, DECIMAL_POINT: 0}
    for raw in values:
        if raw is None:
            continue
        _, body, _ = _split_sign(str(raw))
        if not _NUMBER_BODY.match(body):
            continue
        last_comma, last_dot = body.rfind(","), body.rfind(".")
        if last_comma != -1 and last_dot != -1:
            votes[DECIMAL_COMMA if last_comma > last_dot else DECIMAL_POINT] += 1
        elif last_comma != -1 and _fraction_digits(body, ",") in (1, 2):
            votes[DECIMAL_COMMA] += 1
        elif last_dot != -1 and _fraction_digits(body, ".") in (1, 2):
            votes[DECIMAL_POINT] += 1
        elif last_comma != -1 and body.count(",") > 1:
            votes[DECIMAL_POINT] += 1   # "1,234,567" — commas can only be grouping
        elif last_dot != -1 and body.count(".") > 1:
            votes[DECIMAL_COMMA] += 1   # "1.234.567"
    if votes[DECIMAL_COMMA] and not votes[DECIMAL_POINT]:
        return DECIMAL_COMMA
    if votes[DECIMAL_POINT] and not votes[DECIMAL_COMMA]:
        return DECIMAL_POINT
    return None


def _apply_separator(body: str, decimal_separator: str, raw: str) -> str:
    grouping = DECIMAL_POINT if decimal_separator == DECIMAL_COMMA else DECIMAL_COMMA
    integer, _, fraction = body.rpartition(decimal_separator) if decimal_separator in body else (body, "", "")
    if grouping in fraction or decimal_separator in integer:
        raise AmountParseError(tr("could not parse amount: {amount!r}", amount=raw))
    if grouping in integer:
        groups = integer.split(grouping)
        if not (1 <= len(groups[0]) <= 3 and all(len(g) == 3 for g in groups[1:])):
            raise AmountParseError(tr("could not parse amount: {amount!r} (unexpected digit grouping)", amount=raw))
        integer = "".join(groups)
    return f"{integer}.{fraction}" if fraction else integer


def parse_amount_to_decimal(raw: str, decimal_separator: str | None = None) -> Decimal:
    """Parse an amount string into a Decimal.

    Handles "1.234,56", "1,234.56", "-42,90", "42,90-", "(42,90)",
    "42,90 S"/"42,90 H", "−42,90" (Unicode minus), "€ 45,67", "45.67 EUR".
    Pass `decimal_separator` ("," or ".") when it is known for the whole
    file; without it, values that could be read both ways raise
    AmbiguousAmountError.
    """
    if raw is None:
        raise AmountParseError(tr("empty amount"))
    text = str(raw).strip()
    if not text:
        raise AmountParseError(tr("empty amount"))

    negative, body, _ = _split_sign(text)
    if not body or not _NUMBER_BODY.match(body):
        raise AmountParseError(tr("could not parse amount: {amount!r}", amount=raw))

    if decimal_separator is None:
        last_comma, last_dot = body.rfind(","), body.rfind(".")
        if last_comma != -1 and last_dot != -1:
            decimal_separator = DECIMAL_COMMA if last_comma > last_dot else DECIMAL_POINT
        elif last_comma != -1 or last_dot != -1:
            sep = "," if last_comma != -1 else "."
            digits = _fraction_digits(body, sep)
            if body.count(sep) > 1:
                decimal_separator = DECIMAL_POINT if sep == "," else DECIMAL_COMMA  # repeated => grouping
            elif digits == 3:
                raise AmbiguousAmountError(tr(
                    "amount {amount!r} is ambiguous: '{separator}' could be a decimal or a thousands separator",
                    amount=raw, separator=sep,
                ))
            else:
                decimal_separator = sep
        else:
            decimal_separator = DECIMAL_POINT  # plain integer

    normalized = _apply_separator(body, decimal_separator, text)
    try:
        value = Decimal(normalized)
    except InvalidOperation as exc:
        raise AmountParseError(tr("could not parse amount: {amount!r}", amount=raw)) from exc

    if value != value.quantize(Decimal("0.01")):
        # Sub-cent precision in a bank export almost always means the
        # separator was misread; rounding it away would hide that.
        raise AmountParseError(tr("amount {amount!r} has more than two decimal places", amount=raw))

    return -value if negative else value


def decimal_to_minor_units(value: Decimal, exponent: int = 2) -> int:
    quantized = value.scaleb(exponent)
    return int(quantized.to_integral_value(rounding="ROUND_HALF_UP"))


# One billion: larger than any booking of a private account — and small enough that
# SQLite's 64-bit sums of millions of bookings never overflow.
MAX_AMOUNT_MINOR = 10 ** 11


def parse_amount_to_minor_units(raw: str, decimal_separator: str | None = None) -> int:
    minor = decimal_to_minor_units(parse_amount_to_decimal(raw, decimal_separator))
    if abs(minor) > MAX_AMOUNT_MINOR:
        raise AmountParseError(tr("amount {amount!r} is implausibly large", amount=raw))
    return minor


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def _clean_date_text(raw: str) -> str:
    text = raw.strip()
    # "2026-01-15 00:00:00" / "15.01.2026 13:45" — keep the date part only.
    text = re.sub(r"[ T]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$", "", text)
    return text.strip()


def _strptime(text: str, fmt: str) -> date | None:
    try:
        parsed = datetime.strptime(text, fmt).date()
    except ValueError:
        return None
    # strptime's %Y also accepts 1-3 digit years ("01.02.25" -> year 25).
    if not 1900 <= parsed.year <= 2200:
        return None
    return parsed


def parse_date(raw: str, fmt: str) -> date:
    text = _clean_date_text(raw or "")
    parsed = _strptime(text, fmt) if text else None
    if parsed is None:
        raise DateParseError(tr("could not parse date {date!r} as {format}", date=raw, format=fmt))
    return parsed


def detect_date_format(values: list[str]) -> tuple[str | None, list[str]]:
    """Return (format, candidates) for a column of date strings.

    `format` is the single format that parses every value (or several that
    agree on every value). When more than one format fits but they
    disagree — e.g. all days are <= 12 in a slash-separated file — format
    is None and `candidates` lists the choices for the user. When nothing
    fits every value, both are empty/None and callers fall back to
    per-value parsing (reporting the rows that fail)."""
    texts = [_clean_date_text(v) for v in values if v is not None and str(v).strip()]
    # Cells that aren't a date in ANY format ("Pending", "Total", a footer)
    # are left to per-row reporting; they must not stop the other rows'
    # format from being recognized.
    texts = [t for t in texts if any(_strptime(t, fmt) is not None for fmt in _DATE_FORMATS)]
    if not texts:
        return None, []

    candidates = [fmt for fmt in _DATE_FORMATS if all(_strptime(t, fmt) is not None for t in texts)]
    if not candidates:
        return None, []
    if len(candidates) == 1:
        return candidates[0], candidates

    first = [_strptime(t, candidates[0]) for t in texts]
    if all([_strptime(t, fmt) for t in texts] == first for fmt in candidates[1:]):
        return candidates[0], candidates
    return None, candidates


def parse_date_flexible(raw: str) -> date:
    """Parse a single date without file-level context. Only unambiguous
    interpretations are accepted: "02/03/2026" raises, "15/03/2026" and
    "03/15/2026" don't."""
    if raw is None:
        raise DateParseError(tr("empty date"))
    text = _clean_date_text(str(raw))
    if not text:
        raise DateParseError(tr("empty date"))

    fmt, candidates = detect_date_format([text])
    if fmt is not None:
        return _strptime(text, fmt)
    if candidates:
        raise DateParseError(tr("date {date!r} is ambiguous (could be {formats})", date=raw,
                                formats=tr(" or ").join(candidates)))

    try:
        parsed = datetime.fromisoformat(text).date()
    except ValueError:
        parsed = None
    if parsed is not None and 1900 <= parsed.year <= 2200:
        return parsed

    raise DateParseError(tr("could not parse date: {date!r}", date=raw))
