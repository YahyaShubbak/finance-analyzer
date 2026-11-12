"""Generic bank (checking/savings) statement layout.

Format-agnostic: looks for lines of the shape
`DATE [VALUE-DATE] DESCRIPTION AMOUNT [CURRENCY] [BALANCE]` and a period
header. A reasonable fallback for many real statements and the basis new
bank-specific parsers can be modeled on — it is NOT tuned to any single
real bank's export.
"""
from __future__ import annotations

import re
from functools import lru_cache

from app.db.models import DocumentType
from app.i18n import format_amount, tr
from app.importers.parsing_utils import (
    AmountParseError,
    DateParseError,
    parse_amount_to_minor_units,
    parse_date_flexible,
)
from app.importers.pdf_layouts.base import BasePDFLayoutParser, PDFParsedLine, PDFParseResult
from app.importers.pdf_layouts.patterns import (
    AMOUNT,
    AMOUNT_ONLY_RE,
    BALANCE_LINE_RE,
    DATE_PREFIX_RE,
    SIGNED_AMOUNT_RE,
    VALUE_DATE_LINE_RE,
    amount_has_sign,
    card_title_in_parts,
    complete_date,
    has_split_debit_credit_columns,
    header_zone,
    match_tx_line,
    may_be_missed_booking,
    parse_period,
    reference_date,
)
from app.importers.pdf_layouts.table import TableParse, parse_table

# Balance lines without a date ("Alter Saldo 01.09.2026 +1.234,56").
_OPENING_RE = re.compile(r"^(?:alter (?:saldo|kontostand)|saldo alt|kontostand alt|anfangssaldo|saldo ?vortrag|"
                         r"opening balance|previous balance|balance brought forward)\b", re.IGNORECASE)
_CLOSING_RE = re.compile(r"^(?:neuer (?:saldo|kontostand)|saldo neu|kontostand neu|endsaldo|schlusssaldo|"
                         r"closing balance|new balance|balance carried forward)\b", re.IGNORECASE)
_TRAILING_AMOUNT_RE = re.compile(rf"({AMOUNT})\s*(?:EUR|€)?\s*$")

_HEADER_KEYWORDS = [
    "bank statement", "account statement", "kontoauszug", "girokonto", "iban", "checking account",
    "savings account", "tagesgeld", "sparkonto",
]
# Only phrases that name the DOCUMENT as a card statement. Merely mentioning
# "VISA" or "Mastercard" is common on bank statements (debit cards, the
# monthly card payment) and must not exclude them.
CREDIT_CARD_TITLES = [
    "credit card statement", "kreditkartenabrechnung", "kreditkarten-abrechnung", "kreditkartenumsaetze",
    "kreditkartenumsätze", "minimum payment", "mindestbetrag", "mindestzahlung",
    # "Ihre Kartenabrechnung vom 15.03.2026" (not a bare "Kartenabrechnung": a giro
    # statement's booking text may say that about the card bill it pays)
    "ihre kartenabrechnung", "kartenabrechnung vom",
]


class GenericBankStatementLayout(BasePDFLayoutParser):
    name = "generic_bank_statement_v1"

    def detect(self, full_text: str) -> float:
        top = header_zone(full_text)
        if any(title in top for title in CREDIT_CARD_TITLES) or card_title_in_parts(top):
            return 0.0  # let the credit-card layout claim this document instead
        score = 0.0
        if any(kw in top for kw in _HEADER_KEYWORDS):
            score += 0.4
        tx_line_count = sum(1 for line in full_text.splitlines() if match_tx_line(line.strip()))
        if tx_line_count >= 1:
            score += min(0.6, 0.1 * tx_line_count)
        return min(score, 1.0)

    def parse_pages(self, full_text: str, pages: list[list[tuple]]) -> PDFParseResult:
        """Prefer reading the statement as a table (words assigned to columns
        by position, see pdf_layouts.table); fall back to the text reading.
        The reading whose bookings add up to the statement's balances wins."""
        text_result = self.parse(full_text)
        table = parse_table(pages)
        if table is None:
            return text_result
        table_result = self._result_from_table(full_text, table)
        table_ok = bool(table_result.balance_check and table_result.balance_check["ok"])
        text_ok = bool(text_result.balance_check and text_result.balance_check["ok"])
        if table_ok:
            return table_result
        if text_ok:
            return text_result
        if table_result.balance_check is None and text_result.balance_check is None:
            # nothing to check against: the table reading only if it is complete
            complete = len(table_result.lines) >= len(text_result.lines) and table.unreadable_rows == 0
            return table_result if complete else text_result
        # both fail: the reading that is closer
        table_gap = abs(table_result.balance_check["difference_minor"]) if table_result.balance_check else None
        text_gap = abs(text_result.balance_check["difference_minor"]) if text_result.balance_check else None
        if table_gap is not None and (text_gap is None or table_gap <= text_gap):
            return table_result
        return text_result

    def _result_from_table(self, full_text: str, table: TableParse) -> PDFParseResult:
        period_start, period_end = parse_period(full_text)
        reference = reference_date(full_text, period_end)
        for line in table.lines:
            line.date_text = complete_date(line.date_text, reference)
            if line.value_date_text:
                line.value_date_text = complete_date(line.value_date_text, reference)
        warnings: list[str] = []
        if table.unreadable_rows:
            warnings.append(tr(
                "{count} row(s) with a date but no amount in the amount column could not be read as a booking. "
                "Check them against the statement.", count=table.unreadable_rows,
            ))
        balance_check, sections_with_bookings = _check_balances(table.balance_events, table.lines)
        warnings += _balance_warnings(balance_check, sections_with_bookings)
        return PDFParseResult(
            document_type=DocumentType.BANK_STATEMENT,
            lines=table.lines,
            period_start=period_start,
            period_end=period_end,
            warnings=warnings,
            balance_check=balance_check,
        )

    def parse(self, full_text: str) -> PDFParseResult:
        lines: list[PDFParsedLine] = []
        warnings: list[str] = []
        period_start, period_end = parse_period(full_text)
        reference = reference_date(full_text, period_end)

        balance_lines = 0
        unreadable: list[str] = []
        yearless = False
        text_lines = [raw.strip() for raw in full_text.splitlines()]
        # A line ending in two amounts is "booking, running balance" — or,
        # on statements without a balance column, "number in the text,
        # booking" ("Rechnung 12 345,67 -345,67"). The signs tell, see below;
        # where they don't, the statement's balances decide (_settle_by_balance).
        matches = [m for m in (match_tx_line(line) for line in text_lines) if m]
        single = [m for m in matches if not m.group("balance")]
        amounts_signed = bool(single) and sum(amount_has_sign(m.group("amount")) for m in single) >= 0.8 * len(single)
        idx = 0
        balance_events: list[tuple[int, str, str]] = []  # (line, "open" | "close" | "?", amount)
        while idx < len(text_lines):
            stripped = text_lines[idx]
            m = match_tx_line(stripped)
            if not m:
                kind = "open" if _OPENING_RE.match(stripped) else "close" if _CLOSING_RE.match(stripped) else None
                amount = _TRAILING_AMOUNT_RE.search(stripped) if kind else None
                if amount:
                    balance_events.append((idx, kind, amount.group(1)))
                if may_be_missed_booking(stripped):
                    unreadable.append(stripped)
                idx += 1
                continue
            description = m.group("desc").strip()
            amount_text = m.group("amount")
            alternative = None
            if m.group("balance"):
                first, last = m.group("amount"), m.group("balance")
                # Bookings are signed on this statement, but here only the last number is: it is the
                # booking, the unsigned one before it is text. (A balance column never looks like that.)
                last_is_booking = amounts_signed and amount_has_sign(last) and not amount_has_sign(first)
                as_last = (f"{description} {first}".strip(), last)
                if last_is_booking:
                    description, amount_text = as_last
                    alternative = (m.group("desc").strip(), first)
                else:
                    alternative = as_last
            if BALANCE_LINE_RE.match(description):
                balance_lines += 1  # "Alter Kontostand 1.000,00" is not a transaction
                balance_events.append((idx, _balance_kind(description), amount_text))
                idx += 1
                continue
            yearless = yearless or not re.search(r"\d{2,4}$", m.group("date"))
            line = PDFParsedLine(
                source_row_index=idx,
                date_text=complete_date(m.group("date"), reference),
                description=description,
                amount_text=amount_text,
                currency_text=m.group("currency"),
                alternative=alternative,
                value_date_text=complete_date(m.group("value_date"), reference) if m.group("value_date") else None,
            )
            idx += 1
            idx = _collect_continuation(text_lines, idx, line, reference)
            lines.append(line)

        if not lines:
            warnings.append(tr("No transaction lines matched the generic bank-statement layout."))
        if balance_lines:
            warnings.append(tr("{count} balance line(s) (e.g. opening/closing balance) were skipped.",
                               count=balance_lines))
        if unreadable:
            warnings.append(tr(
                "{count} line(s) starting with a date could not be read as a transaction, "
                "e.g. {example!r}. Check them against the statement.",
                count=len(unreadable), example=unreadable[0][:80],
            ))
        if yearless and reference is None:
            warnings.append(tr("The statement shows dates without a year and no statement period was found, "
                               "so those dates cannot be read."))

        balance_check, sections_with_bookings = _check_balances(balance_events, lines)
        if balance_check and not balance_check["ok"] and _settle_by_balance(balance_events, lines):
            balance_check, sections_with_bookings = _check_balances(balance_events, lines)
        warnings += _balance_warnings(balance_check, sections_with_bookings)

        errors: list[str] = []
        if lines and has_split_debit_credit_columns(full_text) \
                and not any(amount_has_sign(line.amount_text) for line in lines):
            errors.append(tr(
                "This statement prints money in and money out in separate columns without a sign, so the "
                "direction of each amount can't be read reliably from the PDF. Please import the bank's "
                "CSV export of this statement instead."
            ))

        return PDFParseResult(
            document_type=DocumentType.BANK_STATEMENT,
            lines=lines,
            period_start=period_start,
            period_end=period_end,
            warnings=warnings,
            errors=errors,
            balance_check=balance_check,
        )


def _balance_warnings(balance_check: dict | None, sections_with_bookings: int) -> list[str]:
    warnings = []
    if balance_check and not balance_check["ok"]:
        warnings.append(tr(
            "The bookings don't add up: opening balance + bookings differs from the closing balance by "
            "{difference}. A booking may have been missed or misread — please compare with the statement.",
            difference=format_amount(abs(balance_check["difference_minor"])),
        ))
    if sections_with_bookings > 1:
        warnings.append(tr(
            "This statement covers several sub-accounts with their own balances, and more than one has "
            "bookings. All of them are imported into the chosen account."
        ))
    return warnings


def _balance_kind(description: str) -> str:
    low = description.lower()
    if re.search(r"\b(?:alter|alt|anfangs\w*|vortrag|opening|previous|brought)\b", low):
        return "open"
    if re.search(r"\b(?:neuer|neu|end\w*|schluss\w*|closing|new|carried)\b", low):
        return "close"
    return "?"  # "Kontostand am ...": the first one opens, the next closes


_MAX_AMBIGUOUS_LINES = 10


def _settle_by_balance(events: list[tuple[int, str, str]], lines: list[PDFParsedLine]) -> bool:
    """Lines ending in two amounts can be read two ways. If the statement's
    own balances only add up with exactly one combination of readings, use
    that one. Returns whether anything changed."""
    ambiguous = [line for line in lines if line.alternative]
    if not ambiguous or len(ambiguous) > _MAX_AMBIGUOUS_LINES:
        return False
    original = [(line.description, line.amount_text, line.alternative) for line in ambiguous]
    solutions = []
    for mask in range(1, 2 ** len(ambiguous)):
        for bit, line in enumerate(ambiguous):
            description, amount_text, alternative = original[bit]
            if mask >> bit & 1:
                line.description, line.amount_text = alternative
            else:
                line.description, line.amount_text = description, amount_text
        check, _ = _check_balances(events, lines)
        if check and check["ok"]:
            solutions.append(mask)
            if len(solutions) > 1:
                break
    chosen = solutions[0] if len(solutions) == 1 else 0
    for bit, line in enumerate(ambiguous):
        description, amount_text, alternative = original[bit]
        if chosen >> bit & 1:
            line.description, line.amount_text = alternative
            line.alternative = (description, amount_text)
        else:
            line.description, line.amount_text = description, amount_text
    return bool(chosen)


@lru_cache(maxsize=8192)
def _amount_minor(amount_text: str) -> int:
    """parse_amount_to_minor_units, remembered per text: _settle_by_balance
    checks the balances once per combination of readings (up to 1023 times),
    each time over every line of the statement."""
    return parse_amount_to_minor_units(amount_text)


def _check_balances(events: list[tuple[int, str, str]], lines: list[PDFParsedLine]) -> tuple[dict | None, int]:
    """Opening balance + bookings == closing balance, per balance section
    (some statements list sub-accounts one after another). Returns the
    check (None if no section with bookings has both balances) and how
    many sections contain bookings."""
    sections: list[tuple[int, int, int, int]] = []  # (start line, end line, opening, closing)
    opening: tuple[int, int] | None = None
    for line_no, kind, amount_text in sorted(events):
        try:
            amount = _amount_minor(amount_text)
        except AmountParseError:
            continue
        if kind == "open" or (kind == "?" and opening is None):
            opening = (line_no, amount)
        elif opening is not None:
            sections.append((opening[0], line_no, opening[1], amount))
            opening = None
    differences = []
    for start, end, opening_minor, closing_minor in sections:
        members = [line for line in lines if start < line.source_row_index < end]
        if not members:
            continue
        try:
            total = sum(_amount_minor(line.amount_text) for line in members)
        except AmountParseError:
            return None, 0
        differences.append(closing_minor - opening_minor - total)
    if not differences:
        return None, 0
    mismatch = next((d for d in differences if d), 0)
    return {"ok": mismatch == 0, "difference_minor": mismatch}, len(differences)


_MAX_CONTINUATION_LINES = 4
_MAX_VALUE_DATE_GAP_DAYS = 10


def _close_dates(booking: str | None, value: str) -> bool:
    try:
        gap = abs((parse_date_flexible(value) - parse_date_flexible(booking or "")).days)
    except DateParseError:
        return False
    return gap <= _MAX_VALUE_DATE_GAP_DAYS
_PAGE_FURNITURE_RE = re.compile(r"^(?:seite|page|blatt|übertrag|uebertrag|kontostand|saldo|summe)\b", re.IGNORECASE)


def _collect_continuation(text_lines: list[str], idx: int, line: PDFParsedLine, reference) -> int:
    """Many statements (e.g. Sparkasse) print one booking as a block: the
    booking line with the amount, then a line starting with the value date
    that names the payee/purpose, then reference lines. The value-date
    line's text is part of the description (it's what identifies the
    merchant); further lines are kept as details. Stops at the next
    booking, at any other amount, or at page furniture."""
    first = True
    taken = 0
    while idx < len(text_lines) and taken < _MAX_CONTINUATION_LINES:
        text = text_lines[idx]
        if (not text or match_tx_line(text) or _PAGE_FURNITURE_RE.match(text) or AMOUNT_ONLY_RE.search(text)
                or SIGNED_AMOUNT_RE.search(text)):
            break
        value_date = VALUE_DATE_LINE_RE.match(text) if first else None
        if value_date and not _close_dates(line.date_text, complete_date(value_date.group("date"), reference)):
            break  # a different booking's date, not this booking's value date
        if value_date:
            line.value_date_text = line.value_date_text or complete_date(value_date.group("date"), reference)
            rest = value_date.group("rest").strip()
            if rest:
                line.description = f"{line.description} {rest}"
        elif DATE_PREFIX_RE.match(text):
            break  # another dated line that is not this booking's value date
        else:
            line.details.append(text)
        first = False
        taken += 1
        idx += 1
    return idx
