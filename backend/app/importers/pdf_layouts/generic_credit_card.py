"""Generic credit-card statement layout.

Extracts individual purchase/refund lines plus the statement's own
declared total (and, where present, fee/interest/previous-balance lines)
so the reconciliation engine has real data to compare against — never
invented.
"""
from __future__ import annotations

import re

from app.db.models import DocumentType
from app.i18n import tr
from app.importers.parsing_utils import AmountParseError, has_debit_credit_marker, parse_amount_to_minor_units
from app.importers.pdf_layouts.base import BasePDFLayoutParser, PDFParsedLine, PDFParseResult, booked_amount_minor
from app.importers.pdf_layouts.generic_bank import CREDIT_CARD_TITLES
from app.importers.pdf_layouts.patterns import (
    AMOUNT,
    BALANCE_LINE_RE,
    card_title_in_parts,
    complete_date,
    header_zone,
    match_tx_line,
    may_be_missed_booking,
    parse_period,
    reference_date,
)

# Card brand names are weak evidence on their own (bank statements mention
# them too); a real title is strong evidence.
_BRAND_KEYWORDS = ["visa", "mastercard", "amex", "american express"]

_TOTAL_LABELS = {
    "statement total": "statement_total",
    "total due": "statement_total",
    "new balance": "statement_total",
    "neuer saldo": "statement_total",
    "rechnungsbetrag": "statement_total",
    "zu zahlender betrag": "statement_total",
    "neuer kontostand": "statement_total",
}
_OTHER_TOTAL_LABELS = {
    "fee": "fee",
    "annual fee": "fee",
    "jahresgebuehr": "fee",
    "jahresgebühr": "fee",
    "interest": "interest",
    "zinsen": "interest",
    "previous balance": "previous_balance",
    "vorheriger saldo": "previous_balance",
    "saldo vormonat": "previous_balance",
    "alter kontostand": "previous_balance",
}

# Label beginnings, checked in this order ("Saldo des Vormonats" is the
# previous balance, "Saldo des laufenden Monats" the statement total).
_LABEL_PREFIXES = [
    ("saldo des vormonat", "previous_balance"), ("saldo vormonat", "previous_balance"),
    ("vorheriger saldo", "previous_balance"), ("alter saldo", "previous_balance"), ("previous balance", "previous_balance"),
    ("neuer saldo", "statement_total"), ("saldo des", "statement_total"), ("rechnungsbetrag", "statement_total"),
    ("zu zahlender betrag", "statement_total"), ("gesamtbetrag", "statement_total"), ("new balance", "statement_total"),
    ("total due", "statement_total"), ("statement total", "statement_total"),
]


# The marker stands on its own line ("GUTSCHRIFT", "Haben 12,34") or, in
# capitals, at the end of the line below the booking ("4711 0815 GUTSCHRIFT").
# A sentence like "Haben Sie Fragen?" or "credit limit" is no marker.
_AMOUNT_TAIL = r"[\s.:]*(?:[-+]?\s*[\d.,]+\s*(?:EUR|€)?)?\s*$"
_CREDIT_MARKER_END_RE = re.compile(rf"\s(?:GUTSCHRIFT|CREDIT|HABEN|CR){_AMOUNT_TAIL}")
_CREDIT_MARKER_LINE_RE = re.compile(rf"^\s*(?:gutschrift|credit|haben|cr){_AMOUNT_TAIL}", re.IGNORECASE)


def _is_credit_marker(text: str) -> bool:
    return bool(_CREDIT_MARKER_LINE_RE.match(text) or _CREDIT_MARKER_END_RE.search(text))


def _credit_marked_below(text_lines: list[str], idx: int, lookahead: int = 2) -> bool:
    """True when one of the next lines (before the next booking) marks this
    booking as a credit."""
    for text in text_lines[idx + 1: idx + 1 + lookahead]:
        if not text or match_tx_line(text):
            return False
        if _is_credit_marker(text):
            return True
    return False


# "Rechnungsbetrag der Vorperiode", "Saldo der letzten Abrechnung": the
# previous statement's amount, whatever word the label starts with
_PREVIOUS_RE = re.compile(r"vorperiode|vormonat|letzten abrechnung|vorherig|previous")


def _label_kind(label: str) -> str | None:
    if _PREVIOUS_RE.search(label):
        return "previous_balance"
    if label in _TOTAL_LABELS:
        return _TOTAL_LABELS[label]
    if label in _OTHER_TOTAL_LABELS:
        return _OTHER_TOTAL_LABELS[label]
    return next((kind for prefix, kind in _LABEL_PREFIXES if label.startswith(prefix)), None)


# Some issuers (e.g. Landesbank Berlin's Amazon Visa) print the direction
# apart from the amount at the end of the line: "12,50 -" a charge, "300,00 +"
# a credit. Read as the explicit Soll/Haben marker it is ("12,50 S").
_TRAILING_SIGN_RE = re.compile(r"(\d[.,]\d{2})\s+([-+])$")
# ... and the booking date after the text, possibly followed by the original
# currency, amount and rate: "Supermarkt Beispiel Musterstadt 04.03.2026",
# "Hotel Example London 06.03.2026 GBP 100,00 0,8500".
_BOOKED_AFTER_TEXT_RE = re.compile(
    r"^(?P<text>.+?)\s+(?P<booked>\d{2}\.\d{2}\.\d{4})"
    r"(?:\s+(?P<original>[A-Z]{3}\s+[\d.,]+)\s+(?P<rate>\d+,\d+))?$"
)
# A line without a purchase date — the payment onto the card, booked on a
# date: "ZAHLUNG-LASTSCHRIFT 20.03.2026 1.234,56 +".
_TEXT_DATE_AMOUNT_RE = re.compile(rf"^(?P<desc>[^\d\s].*?)\s+(?P<date>\d{{2}}\.\d{{2}}\.\d{{4}})\s+(?P<amount>{AMOUNT})$")


def _sign_as_marker(line: str) -> str:
    return _TRAILING_SIGN_RE.sub(lambda m: f"{m.group(1)} {'S' if m.group(2) == '-' else 'H'}", line)


# "Neuer Saldo: 1.234,56", "Gesamtbetrag 15.10.2026 EUR 426,50" (a date after the label)
_LABELED_AMOUNT_RE = re.compile(
    rf"^([A-Za-zÄÖÜäöüß ]+?)(?:\s+\d{{2}}\.\d{{2}}\.(?:\d{{4}}|\d{{2}}))?\s*[:\-]?\s*({AMOUNT})\s*(?:EUR|USD|GBP|CHF|€|\$|£)?\s*$"
)


# A fee printed as its own line, without a date, under the purchase it is
# charged for: "AUSLANDSEINSATZENTGELT 0,61 -" (a separate booking).
_FEE_LINE_RE = re.compile(
    rf"^(?P<desc>[^\d]*?(?:entgelt|gebühr|gebuehr|fee|zuschlag|provision)[^\d]*?)\s+(?P<amount>{AMOUNT})$",
    re.IGNORECASE,
)
_NOT_A_FEE_RE = re.compile(r"(?i)\b(?:summe|gesamt|total)\b")


class GenericCreditCardStatementLayout(BasePDFLayoutParser):
    name = "generic_credit_card_statement_v1"

    def detect(self, full_text: str) -> float:
        top = header_zone(full_text)
        score = 0.0
        if any(title in top for title in CREDIT_CARD_TITLES) or card_title_in_parts(top):
            score += 0.5
        elif any(brand in top for brand in _BRAND_KEYWORDS):
            score += 0.1
        tx_line_count = sum(1 for line in full_text.splitlines() if match_tx_line(line.strip()))
        if tx_line_count >= 1:
            score += min(0.5, 0.1 * tx_line_count)
        return min(score, 1.0)

    def parse(self, full_text: str) -> PDFParseResult:
        lines: list[PDFParsedLine] = []
        warnings: list[str] = []
        statement_total_minor: int | None = None
        other_totals: dict[str, int] = {}
        period_start, period_end = parse_period(full_text)
        reference = reference_date(full_text, period_end)
        unreadable: list[str] = []
        yearless = False
        signed_balances: dict[str, int] = {}  # in the app's sign: negative = owed
        printed: dict[str, int] = {}  # the balances as printed without S/H marker ("-191,02": a credit)

        text_lines = [_sign_as_marker(raw.strip()) for raw in full_text.splitlines()]
        for idx, stripped in enumerate(text_lines):
            if not stripped:
                continue

            tx_match = match_tx_line(stripped)
            if tx_match:
                description = tx_match.group("desc").strip()
                if BALANCE_LINE_RE.match(description):
                    continue  # e.g. "01.09.2026 Saldo vom Vormonat 100,00"
                value_date_text = tx_match.group("value_date")
                booked = None if value_date_text else _BOOKED_AFTER_TEXT_RE.match(description)
                if booked:
                    description, value_date_text = booked.group("text"), booked.group("booked")
                    if booked.group("original"):
                        description = f"{description} ({booked.group('original')}, {booked.group('rate')})"
                amount_text, currency_text = tx_match.group("amount"), tx_match.group("currency")
                if tx_match.group("balance"):
                    # Card statements don't print a running balance; two
                    # amounts mean "original foreign amount, booked amount"
                    # ("USD 12,00 11,06" / "200,00 USD 184,33"). The booked
                    # (last) one is in the card's currency.
                    original = f"{amount_text} {currency_text or ''}".strip()
                    description = f"{description} ({original})"
                    amount_text, currency_text = tx_match.group("balance"), None
                yearless = yearless or not re.search(r"\d{2,4}$", tx_match.group("date"))
                lines.append(PDFParsedLine(
                    source_row_index=idx,
                    date_text=complete_date(tx_match.group("date"), reference),
                    description=description,
                    amount_text=amount_text,
                    currency_text=currency_text,
                    value_date_text=value_date_text,
                    credit_marker=_credit_marked_below(text_lines, idx),
                ))
                continue
            payment = _TEXT_DATE_AMOUNT_RE.match(stripped)
            if payment and has_debit_credit_marker(payment.group("amount")) \
                    and not BALANCE_LINE_RE.match(payment.group("desc")):
                lines.append(PDFParsedLine(
                    source_row_index=idx, date_text=payment.group("date"),
                    description=payment.group("desc").strip(), amount_text=payment.group("amount"),
                ))
                continue
            fee = _FEE_LINE_RE.match(stripped)
            if fee and lines and idx - lines[-1].source_row_index <= 3 and not _NOT_A_FEE_RE.search(fee.group("desc")):
                lines.append(PDFParsedLine(
                    source_row_index=idx, date_text=lines[-1].date_text,
                    description=fee.group("desc").strip(), amount_text=fee.group("amount"),
                    value_date_text=lines[-1].value_date_text,
                ))
                continue
            if may_be_missed_booking(stripped):
                unreadable.append(stripped)
                continue

            label_match = _LABELED_AMOUNT_RE.match(stripped)
            if label_match:
                label, amount_text = label_match.groups()
                label_norm = label.strip().lower()
                try:
                    minor = parse_amount_to_minor_units(amount_text)
                except AmountParseError:
                    continue
                kind = _label_kind(label_norm)
                if kind in ("statement_total", "previous_balance"):
                    if has_debit_credit_marker(amount_text):
                        # "1.523,80 -" owed, "303,09 +" a credit balance (the overview box may print it unsigned)
                        signed_balances.setdefault(kind, minor)
                    else:
                        printed.setdefault(kind, minor)
                if kind == "statement_total" and statement_total_minor is None:
                    statement_total_minor = abs(minor)
                elif kind and kind != "statement_total":
                    other_totals[kind] = abs(minor)

        if unreadable:
            warnings.append(tr(
                "{count} line(s) starting with a date could not be read as a transaction, "
                "e.g. {example!r}. Check them against the statement.",
                count=len(unreadable), example=unreadable[0][:80],
            ))
        if yearless and reference is None:
            warnings.append(tr("The statement shows dates without a year and no statement period was found, "
                               "so those dates cannot be read."))
        if not lines:
            warnings.append(tr("No transaction lines matched the generic credit-card layout."))
        balance_check = None
        closing, opening = signed_balances.get("statement_total"), signed_balances.get("previous_balance")
        if closing is None and opening is None and {"statement_total", "previous_balance"} <= printed.keys():
            # without S/H: on a card statement a plain amount is owed, a negative one a credit
            closing, opening = -printed["statement_total"], -printed["previous_balance"]
        if closing is not None and closing >= 0:
            statement_total_minor = 0  # a credit balance (or none): nothing is debited for this statement
        if closing is not None and opening is not None and lines:
            booked = 0
            for line in lines:
                try:
                    booked += booked_amount_minor(line.amount_text, card_statement=True,
                                                  credit_marker=line.credit_marker)
                except AmountParseError:
                    booked = None
                    break
            if booked is not None:
                difference = closing - opening - booked
                balance_check = {"ok": difference == 0, "difference_minor": difference}
        if statement_total_minor is None:
            warnings.append(tr("No statement total line detected — reconciliation will be limited."))

        return PDFParseResult(
            document_type=DocumentType.CREDIT_CARD_STATEMENT,
            lines=lines,
            period_start=period_start,
            period_end=period_end,
            statement_total_minor=statement_total_minor,
            other_totals=other_totals,
            warnings=warnings,
            balance_check=balance_check,
        )
