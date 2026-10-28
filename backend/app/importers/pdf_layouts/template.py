"""Reading a PDF with a template the user taught in the import review.

When no built-in reader understands a statement, the user shows the app one
booking line and says which of its words are the purchase date, the booking
date, the text, the amount and the sign; picks how unsigned amounts are to
be read; clicks lines to ignore (e.g. "+4 SHOP PUNKTE"); and points at the
line with the statement total or the balances. That template is stored with
the file kind's parse options and read here — deterministic, by word
positions, like the built-in table reader:

* a booking line has a date where the example's purchase date starts and an
  amount ending where the example's amount ends;
* lines below it (not dated, not ignored) are its details;
* the amount's direction follows the template's sign rule.
"""
from __future__ import annotations

import re

from app.db.models import DocumentType
from app.i18n import tr
from app.importers.parsing_utils import AmountParseError, parse_amount_to_minor_units
from app.importers.pdf_layouts.base import PDFParsedLine, PDFParseResult, booked_amount_minor
from app.importers.pdf_layouts.patterns import complete_date, parse_period, reference_date

_DATE_RE = re.compile(r"^\d{1,2}[./]\d{1,2}[./]?(?:\d{2,4})?$")
_AMOUNT_RE = re.compile(r"^[-+−]?\(?(?:\d{1,3}(?:[.,' ]\d{3})+|\d+)[.,]\d{2}\)?[-+]?$")
_SIGN_WORDS = {"-": True, "−": True, "+": False, "S": True, "H": False, "DR": True, "CR": False,
               "SOLL": True, "HABEN": False}
_CREDIT_WORDS = re.compile(r"(?i)\b(?:gutschrift|credit|haben)\b")

#: how far (points) a word may be from the example's position and still be in that column
_DATE_TOLERANCE = 8.0
_AMOUNT_TOLERANCE = 12.0
SIGN_RULES = ("as_printed", "unsigned_is_expense", "unsigned_is_income")


def _lines(pages: list[list[tuple]]) -> list[tuple[int, int, list[tuple]]]:
    """(line index as in the extracted text, page, words sorted by x)."""
    from app.importers.pdf_importer import _group_lines  # the same line grouping as the text

    out, index = [], 0
    for page_no, words in enumerate(pages):
        if not words:
            index += 1
            continue
        for line in _group_lines(words):
            out.append((index, page_no, line))
            index += 1
    return out


def _normalized(text: str) -> str:
    """A line's text without numbers, for matching lines to ignore."""
    return " ".join(re.sub(r"[\d.,+\-−]+", " ", text).upper().split())


def _signed(amount: str, sign_word: str | None, rule: str, credit_below: bool) -> tuple[str, bool]:
    """The amount as text with an explicit direction marker ("12,34 S" = money
    out, "12,34 H" = money in) — kept as is by the importer — and whether it
    could be read."""
    text = amount.replace("−", "-")
    negative = None
    if text.startswith("-") or text.endswith("-") or (text.startswith("(") and text.endswith(")")):
        negative = True
    elif text.startswith("+") or text.endswith("+"):
        negative = False
    if sign_word is not None:
        negative = _SIGN_WORDS[sign_word.upper()]
    if negative is None:
        # printed without a sign: money in — unless the user said such amounts are expenses
        negative = rule == "unsigned_is_expense" and not credit_below
    bare = text.strip("+-() ")
    try:
        parse_amount_to_minor_units(bare)
    except AmountParseError:
        return amount, False
    return f"{bare} {'S' if negative else 'H'}", True


def _labelled_amount(words: list[tuple]) -> tuple[str, str | None] | None:
    amounts = [i for i, w in enumerate(words) if _AMOUNT_RE.match(w[4])]
    if not amounts:
        return None
    i = amounts[-1]
    sign = words[i + 1][4] if i + 1 < len(words) and words[i + 1][4].upper() in _SIGN_WORDS else None
    return words[i][4], sign


def parse_with_template(template: dict, full_text: str, pages: list[list[tuple]]) -> PDFParseResult:
    columns = template.get("columns") or {}
    date_col, amount_col = columns.get("date"), columns.get("amount")
    if not date_col or not amount_col:
        return PDFParseResult(
            document_type=DocumentType.UNKNOWN, lines=[],
            errors=[tr("The template needs at least the date and the amount of a booking.")],
        )
    value_col, text_col, sign_col = columns.get("value_date"), columns.get("text"), columns.get("sign")
    rule = template.get("sign_rule") if template.get("sign_rule") in SIGN_RULES else "as_printed"
    ignore = {_normalized(p) for p in (template.get("ignore") or [])} - {""}
    labels = {k: _normalized(v) for k, v in (template.get("labels") or {}).items() if v}
    document_type = (DocumentType.CREDIT_CARD_STATEMENT if template.get("document_type") == "credit_card_statement"
                     else DocumentType.BANK_STATEMENT)

    period_start, period_end = parse_period(full_text)
    reference = reference_date(full_text, period_end)
    lines: list[PDFParsedLine] = []
    totals: dict[str, int] = {}
    warnings: list[str] = []
    current: PDFParsedLine | None = None
    current_page = -1
    skipped = 0

    all_lines = _lines(pages)
    for position, (index, page, words) in enumerate(all_lines):
        text = " ".join(w[4] for w in words)
        normalized = _normalized(text)
        if page != current_page:
            current, current_page = None, page
        if normalized in ignore:
            continue
        label = next((kind for kind, lab in labels.items() if lab and normalized.startswith(lab)), None)
        if label:
            current = None
            found = _labelled_amount(words)
            if found:
                signed, ok = _signed(found[0], found[1], "as_printed", False)
                if ok:
                    minor = parse_amount_to_minor_units(signed)
                    totals[label] = minor
            continue

        date_word = next((w for w in words if abs(w[0] - date_col[0]) <= _DATE_TOLERANCE and _DATE_RE.match(w[4])), None)
        amount_index = next((i for i in range(len(words) - 1, -1, -1)
                             if abs(words[i][2] - amount_col[1]) <= _AMOUNT_TOLERANCE and _AMOUNT_RE.match(words[i][4])), None)
        if date_word is not None and amount_index is not None:
            amount_word = words[amount_index]
            sign_word = None
            for w in words[amount_index + 1:]:
                in_sign_column = sign_col and abs(w[0] - sign_col[0]) <= _DATE_TOLERANCE
                if (in_sign_column or w[0] - amount_word[2] <= 20) and w[4].upper() in _SIGN_WORDS:
                    sign_word = w[4]
                    break
            value_word = next((w for w in words if value_col and w is not date_word
                               and abs(w[0] - value_col[0]) <= _DATE_TOLERANCE and _DATE_RE.match(w[4])), None)
            used = {id(date_word), id(amount_word), id(value_word)}
            text_words = [w for w in words if id(w) not in used and w[2] <= amount_word[0] + 1
                          and w[4] != sign_word and (not text_col or w[0] >= text_col[0] - _DATE_TOLERANCE)]
            following = all_lines[position + 1][2] if position + 1 < len(all_lines) else []
            credit_below = bool(_CREDIT_WORDS.search(" ".join(w[4] for w in following))) and not any(
                _DATE_RE.match(w[4]) for w in following[:1])
            amount_text, ok = _signed(amount_word[4], sign_word, rule, credit_below)
            if not ok:
                skipped += 1
                continue
            current = PDFParsedLine(
                source_row_index=index,
                date_text=complete_date(date_word[4], reference),
                description=" ".join(w[4] for w in text_words).strip() or None,
                amount_text=amount_text,
                value_date_text=complete_date(value_word[4], reference) if value_word else None,
            )
            lines.append(current)
            continue
        if date_word is not None and amount_index is None:
            skipped += 1
        if current is not None and date_word is None and len(current.details) < 4 and not _AMOUNT_RE.match(words[-1][4]):
            current.details.append(text)

    if skipped:
        warnings.append(tr("{count} dated line(s) did not fit the template — check them in the review.", count=skipped))
    if not lines:
        warnings.append(tr("No booking matched the template."))

    statement_total = abs(totals["total"]) if "total" in totals else None
    balance_check = None
    if "opening" in totals and "closing" in totals:
        booked = sum(booked_amount_minor(line.amount_text, document_type == DocumentType.CREDIT_CARD_STATEMENT)
                     for line in lines)
        difference = totals["closing"] - totals["opening"] - booked
        balance_check = {"ok": difference == 0, "difference_minor": difference}
    return PDFParseResult(
        document_type=document_type,
        lines=lines,
        period_start=period_start,
        period_end=period_end,
        statement_total_minor=statement_total,
        other_totals={"previous_balance": abs(totals["opening"])} if "opening" in totals and statement_total else {},
        warnings=warnings,
        balance_check=balance_check,
    )
