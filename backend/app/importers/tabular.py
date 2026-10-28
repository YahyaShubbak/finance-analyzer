"""Shared parsing core for row-based files (CSV and XLSX).

Both importers only differ in how they obtain rows of cells; everything
after that — finding the header row, mapping columns, deciding the date
format and decimal separator for the whole file, combining debit/credit
columns and normalizing currencies — happens here, so the two formats
can never drift apart.

Cells are plain strings for CSV; XLSX cells may already be typed
(date/datetime/int/float/Decimal), which are used directly.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.db.models import DocumentType
from app.i18n import tr
from app.importers.base import ImportIssue, ParsedImport, ParsedTransaction, ParseOptions
from app.importers.column_detection import (
    LOGICAL_FIELDS,
    detect_bank_format,
    detect_columns,
    detect_header_row,
    mapping_is_ambiguous,
)
from app.importers.currency import normalize_currency
from app.importers.parsing_utils import (
    DATE_FORMATS,
    MAX_AMOUNT_MINOR,
    AmbiguousAmountError,
    AmountParseError,
    DateParseError,
    decimal_to_minor_units,
    detect_date_format,
    detect_decimal_separator,
    parse_amount_to_decimal,
    parse_date,
    parse_date_flexible,
)
from app.importers.pdf_layouts.patterns import BALANCE_LINE_RE

# Columns whose values are consumed into dedicated fields rather than kept
# as "extra" raw data.
_CONSUMED_FIELDS = {"date", "amount", "debit", "credit", "currency", "description", "merchant_category"}


def cell_text(cell: Any) -> str | None:
    if cell is None:
        return None
    if isinstance(cell, datetime):
        return cell.date().isoformat() if cell.time() == datetime.min.time() else cell.isoformat()
    if isinstance(cell, date):
        return cell.isoformat()
    text = str(cell).strip()
    return text or None


def _is_number(cell: Any) -> bool:
    return isinstance(cell, (int, float, Decimal)) and not isinstance(cell, bool)


def _unique_headers(row: list[Any]) -> list[str]:
    """Header names, made unique (ING exports contain two "Währung"
    columns) and never empty, so every column is addressable by name."""
    seen: dict[str, int] = {}
    headers = []
    for index, cell in enumerate(row):
        # Not translated: the name identifies the column in a mapping, which
        # must stay valid when the language is switched in between.
        name = cell_text(cell) or f"Column {index + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        headers.append(name)
    return headers


# A statement or export has at most some thousand rows; far beyond that a file
# would only tie up the computer (a spreadsheet packs millions of cells in a
# small file).
MAX_TABLE_ROWS = 100_000
MAX_TABLE_CELLS = 3_000_000


def too_large(filename: str, checksum: str) -> ParsedImport:
    return _error_result(filename, checksum, tr(
        "The file is too large to be a statement (more than {rows} rows or {cells} cells). "
        "Please export a shorter period.", rows=f"{MAX_TABLE_ROWS:,}".replace(",", "."),
        cells=f"{MAX_TABLE_CELLS:,}".replace(",", ".")))


def _error_result(filename: str, checksum: str, message: str, **kwargs) -> ParsedImport:
    return ParsedImport(
        filename=filename, file_checksum=checksum, document_type=DocumentType.BANK_STATEMENT,
        detected_columns={}, transactions=[], issues=[ImportIssue(severity="error", message=message)],
        ambiguous=True, **kwargs,
    )


_BALANCE_REST_RE = re.compile(r"^[\s:.,]*(?:(?:am|vom|per|zum|on|as of)\s*)?[\d.,/\s+-]*(?:eur|€)?[\s:.,]*$", re.IGNORECASE)


def _is_balance_label(text: str) -> bool:
    """"Anfangssaldo", "Kontostand am 31.03.2026", "Closing balance" — but not
    a booking that merely starts with such a word ("Saldo der Abschlussposten",
    "Kontostand-Benachrichtigung" fees)."""
    m = BALANCE_LINE_RE.match(text)
    return bool(m) and bool(_BALANCE_REST_RE.match(text[m.end():]))


# rows shown in the import review — enough to check a file, not a whole history
_MAX_SOURCE_ROWS = 2000


def parse_rows(rows: list[list[Any]], *, filename: str, checksum: str, options: ParseOptions) -> ParsedImport:
    rows = [list(r) if r is not None else [] for r in rows]
    if not any(cell_text(c) for row in rows for c in row):
        return _error_result(filename, checksum, tr("File is empty."))

    issues: list[ImportIssue] = []

    # --- header row & column mapping -------------------------------------
    header_index = options.header_row
    if header_index is None:
        header_index = detect_header_row(rows)
    if header_index is None:
        header_index = next(i for i, row in enumerate(rows) if any(cell_text(c) for c in row))
    if not 0 <= header_index < len(rows):
        return _error_result(filename, checksum,
                             tr("Header row {number} does not exist in this file.", number=header_index + 1))

    headers = _unique_headers(rows[header_index])
    bank_format = detect_bank_format(headers)
    mapping = detect_columns(headers)
    if options.column_mapping is not None:
        for logical_field in LOGICAL_FIELDS:
            if logical_field not in options.column_mapping:
                continue
            chosen = options.column_mapping[logical_field] or None
            if chosen is not None and chosen not in headers:
                return _error_result(filename, checksum, tr("Column {column!r} does not exist in this file.", column=chosen),
                                     available_columns=headers, header_row_index=header_index)
            mapping[logical_field] = chosen
    if mapping_is_ambiguous(mapping):
        # Without a usable mapping every row would just produce follow-up
        # warnings; the user has to map the columns first.
        return ParsedImport(
            filename=filename, file_checksum=checksum, document_type=DocumentType.BANK_STATEMENT,
            detected_columns=mapping, transactions=[], ambiguous=True,
            issues=[ImportIssue(
                severity="warning",
                message=tr("Could not identify the date, amount and description columns. Please map them manually."),
            )],
            detected_layout=bank_format.name if bank_format else None,
            available_columns=headers, header_row_index=header_index,
        )
    ambiguous = False

    column_index = {h: i for i, h in enumerate(headers)}

    def cell(row: list[Any], logical_field: str) -> Any:
        header = mapping.get(logical_field)
        if not header:
            return None
        index = column_index[header]
        return row[index] if index < len(row) else None

    data_rows = [
        (offset, row) for offset, row in enumerate(rows[header_index + 1:])
        if any(cell_text(c) for c in row)
    ]

    # --- file-level date format --------------------------------------------
    date_format = options.date_format or (bank_format.date_format if bank_format else None)
    if date_format is not None and date_format not in DATE_FORMATS:
        return _error_result(filename, checksum, tr("Unsupported date format {format!r}.", format=date_format))
    date_candidates: list[str] = []
    text_dates = [c for _, r in data_rows if isinstance(c := cell(r, "date"), str) and c.strip()]
    date_ambiguous = False
    if date_format is None and text_dates:
        date_format, date_candidates = detect_date_format(text_dates)
        if date_format is None and len(date_candidates) > 1:
            ambiguous = date_ambiguous = True
            issues.append(ImportIssue(
                severity="warning",
                message=tr("The date format is ambiguous (e.g. 02/03 could be 2 March or 3 February). "
                           "Please choose the date format."),
            ))
    value_date_format, _ = detect_date_format(
        [c for _, r in data_rows if isinstance(c := cell(r, "value_date"), str) and c.strip()]
    )

    # --- file-level decimal separator ---------------------------------------
    amount_texts = [
        c for _, r in data_rows for f in ("amount", "debit", "credit")
        if isinstance(c := cell(r, f), str) and c.strip()
    ]
    decimal_separator = (
        options.decimal_separator
        or (bank_format.decimal_separator if bank_format else None)
        or detect_decimal_separator(amount_texts)
    )
    needs_decimal_separator = False
    if decimal_separator is None:
        for text in amount_texts:
            try:
                parse_amount_to_decimal(text)
            except AmbiguousAmountError:
                needs_decimal_separator = True
                break
            except AmountParseError:
                continue
        if needs_decimal_separator:
            ambiguous = True
            issues.append(ImportIssue(
                severity="warning",
                message=tr("Amounts like \"1.500\" or \"1,234\" could use either decimal separator. "
                           "Please choose the decimal separator."),
            ))

    def amount_minor(raw: Any) -> int:
        if _is_number(raw):
            value = Decimal(str(raw))
            if value != value.quantize(Decimal("0.01")):
                # Same rule as for text: sub-cent precision means a wrong
                # column or a formula, never a bank amount.
                raise AmountParseError(tr("amount {amount!r} has more than two decimal places", amount=raw))
            minor = decimal_to_minor_units(value)
        else:
            minor = decimal_to_minor_units(parse_amount_to_decimal(str(raw), decimal_separator))
        if abs(minor) > MAX_AMOUNT_MINOR:
            raise AmountParseError(tr("amount {amount!r} is implausibly large", amount=raw))
        return minor

    indicator_header = mapping.get("sign_indicator") or _sign_indicator_column(
        headers, mapping, [r for _, r in data_rows], column_index
    )

    def parse_date_cell(raw: Any, fmt: str | None) -> date:
        if isinstance(raw, datetime):
            return raw.date()
        if isinstance(raw, date):
            return raw
        text = str(raw)
        return parse_date(text, fmt) if fmt else parse_date_flexible(text)

    # --- rows ---------------------------------------------------------------
    transactions: list[ParsedTransaction] = []
    ignored_rows = balance_rows = pending_rows = 0
    unknown_currencies: set[str] = set()
    min_date = max_date = None

    for offset, row in data_rows:
        date_raw = cell(row, "date")
        amount_cells = {f: cell(row, f) for f in ("amount", "debit", "credit")}
        if cell_text(date_raw) is None and not any(cell_text(v) for v in amount_cells.values()):
            ignored_rows += 1  # e.g. a "closing balance" footer line
            continue
        date_text = cell_text(date_raw) or ""
        texts = [date_text] + [
            cell_text(cell(row, f)) or "" for f in ("description", "counterparty", "payee", "payer", "booking_text")
        ]
        if any(_is_balance_label(t) for t in texts):
            balance_rows += 1  # "Anfangssaldo"/"Endsaldo" rows state a balance, not a transaction
            continue
        if _SUMMARY_RE.match(date_text) or (texts[1] and _SUMMARY_RE.match(texts[1]) and not date_text):
            ignored_rows += 1  # "Total"/"Summe" footer
            continue
        status_text = cell_text(cell(row, "status"))
        if (status_text and _NOT_BOOKED_RE.search(status_text)) or _PENDING_DATE_RE.match(date_text):
            pending_rows += 1  # appears again, booked, in a later export (comdirect: date "offen")
            continue

        ptx = ParsedTransaction(
            source_row_index=offset,
            original_date_text=cell_text(date_raw),
            original_description=None,
            original_amount_text=None,
        )

        if cell_text(date_raw) is None:
            issues.append(ImportIssue(severity="warning", message=tr("Row {row}: missing date.", row=offset),
                                      row_index=offset))
        else:
            try:
                parsed_date = parse_date_cell(date_raw, date_format)
                ptx.parsed_date = parsed_date.isoformat()
                min_date = parsed_date if min_date is None or parsed_date < min_date else min_date
                max_date = parsed_date if max_date is None or parsed_date > max_date else max_date
            except (DateParseError, ValueError):
                if not date_ambiguous:  # otherwise the single "choose the date format" notice says it all
                    issues.append(ImportIssue(
                        severity="warning",
                        message=tr("Row {row}: could not parse date {date!r}.", row=offset, date=cell_text(date_raw)),
                        row_index=offset,
                    ))

        try:
            ptx.parsed_amount_minor, ptx.original_amount_text = _row_amount(
                amount_cells, mapping, amount_minor, issues, offset
            )
            if ptx.parsed_amount_minor is not None:
                ptx.parsed_amount_minor = _apply_sign_rules(
                    ptx.parsed_amount_minor, row, column_index, indicator_header, mapping, bank_format,
                    amount_minor, options,
                )
        except AmbiguousAmountError:
            pass  # reported once at file level (needs_decimal_separator)
        except (AmountParseError, ValueError, ArithmeticError) as exc:
            issues.append(ImportIssue(severity="warning", message=tr("Row {row}: {problem}.", row=offset, problem=exc),
                                      row_index=offset))

        currency_text = cell_text(cell(row, "currency"))
        ptx.original_currency_text = currency_text
        if currency_text:
            ptx.parsed_currency = normalize_currency(currency_text)
            if ptx.parsed_currency is None:
                unknown_currencies.add(currency_text)

        amount_sign = ptx.parsed_amount_minor or 0
        payee, payer = cell_text(cell(row, "payee")), cell_text(cell(row, "payer"))
        if payee or payer:
            ptx.counterparty = (payee or payer) if amount_sign < 0 else (payer or payee)
        else:
            ptx.counterparty = cell_text(cell(row, "counterparty"))
        iban = cell_text(cell(row, "counterparty_iban"))
        ptx.counterparty_iban = iban.replace(" ", "").upper() if iban else None

        description = cell_text(cell(row, "description"))
        if description and not re.search(r"\w", description):
            description = None  # N26 writes "-" for "no reference"
        ptx.original_description = description or ptx.counterparty or cell_text(cell(row, "booking_text"))

        extra: dict[str, str] = {}
        consumed = {mapping.get(f) for f in _CONSUMED_FIELDS}
        for header, value in zip(headers, row, strict=False):  # short rows are common
            text = cell_text(value)
            if text and header not in consumed:
                extra[header] = text
        if ptx.counterparty:
            extra["_counterparty"] = ptx.counterparty
        merchant_category = cell_text(cell(row, "merchant_category"))
        if merchant_category:
            extra["_merchant_category"] = merchant_category
        booking_text = cell_text(cell(row, "booking_text"))
        if booking_text:
            extra["_booking_text"] = booking_text
        value_date_raw = cell(row, "value_date")
        if cell_text(value_date_raw):
            try:
                extra["_value_date"] = parse_date_cell(value_date_raw, value_date_format).isoformat()
            except (DateParseError, ValueError):
                pass
        ptx.extra_fields = extra

        transactions.append(ptx)

    if ignored_rows:
        issues.append(ImportIssue(
            severity="warning",
            message=tr("{count} row(s) without date and amount were ignored (e.g. balance or summary lines).",
                       count=ignored_rows),
        ))
    if balance_rows:
        issues.append(ImportIssue(
            severity="warning",
            message=tr("{count} balance row(s) (e.g. opening/closing balance) were skipped.", count=balance_rows),
        ))
    if pending_rows:
        issues.append(ImportIssue(
            severity="warning",
            message=tr("{count} pending or cancelled row(s) were skipped — booked transactions appear "
                       "in a later export.", count=pending_rows),
        ))
    for currency in sorted(unknown_currencies):
        issues.append(ImportIssue(
            severity="warning",
            message=tr("Unknown currency {currency!r} — the account's currency will be used for these rows.",
                       currency=currency),
        ))
    if not transactions:
        issues.append(ImportIssue(severity="error", message=tr("No transaction rows detected.")))
        ambiguous = True

    # the original rows, header first, for the import review (row i+1 = source_row_index i)
    source_rows = [[cell_text(c) or "" for c in row] for row in rows[header_index:header_index + 1 + _MAX_SOURCE_ROWS]]
    for ptx in transactions:
        if ptx.source_row_index < _MAX_SOURCE_ROWS:
            ptx.location = {"row": ptx.source_row_index + 1}

    return ParsedImport(
        filename=filename,
        file_checksum=checksum,
        document_type=DocumentType.BANK_STATEMENT,
        detected_columns=mapping,
        source_rows=source_rows,
        transactions=transactions,
        issues=issues,
        period_start=min_date.isoformat() if min_date else None,
        period_end=max_date.isoformat() if max_date else None,
        ambiguous=ambiguous,
        detected_layout=bank_format.name if bank_format else None,
        available_columns=headers,
        header_row_index=header_index,
        date_format=date_format,
        date_format_candidates=date_candidates,
        decimal_separator=decimal_separator,
        needs_decimal_separator=needs_decimal_separator,
    )


def _row_amount(cells: dict[str, Any], mapping, amount_minor, issues: list[ImportIssue], offset: int):
    """Returns (signed amount in minor units or None, original amount text)."""
    if mapping.get("amount") and (cell_text(cells["amount"]) is not None
                                  or not (mapping.get("debit") or mapping.get("credit"))):
        raw = cells["amount"]
        text = cell_text(raw)
        if text is None:
            issues.append(ImportIssue(severity="warning", message=tr("Row {row}: missing amount.", row=offset),
                                      row_index=offset))
            return None, None
        return amount_minor(raw), text
    # Otherwise (no amount column, or it is empty in this row while debit/
    # credit columns exist): combine debit and credit.

    debit_raw, credit_raw = cells["debit"], cells["credit"]
    debit_text, credit_text = cell_text(debit_raw), cell_text(credit_raw)
    if debit_text is None and credit_text is None:
        issues.append(ImportIssue(severity="warning", message=tr("Row {row}: missing amount.", row=offset),
                                  row_index=offset))
        return None, None

    # Debit columns hold money leaving the account — as a positive
    # magnitude in most exports, but some write it with a minus sign, so
    # the magnitude is what counts. Many exports fill the unused column
    # with 0,00, so both columns are always read.
    debit = abs(amount_minor(debit_raw)) if debit_text else 0
    credit = amount_minor(credit_raw) if credit_text else 0
    if debit and credit:
        issues.append(ImportIssue(
            severity="warning",
            message=tr("Row {row}: both debit ({debit}) and credit ({credit}) are filled; using credit minus debit.",
                       row=offset, debit=debit_text, credit=credit_text),
            row_index=offset,
        ))
    original = " / ".join(t for t in (f"-{debit_text.lstrip('-')}" if debit else None,
                                       credit_text if credit else None) if t) or (credit_text or debit_text)
    return credit - debit, original


_INDICATOR_NEGATIVE = {"S", "D", "DR", "SOLL", "DEBIT", "-"}
_INDICATOR_POSITIVE = {"H", "C", "CR", "HABEN", "CREDIT", "+"}
_SUMMARY_RE = re.compile(r"^(?:total|summe|gesamt|sum|zwischensumme)\b", re.IGNORECASE)
_PENDING_DATE_RE = re.compile(r"^(?:offen|vorgemerkt|pending)$", re.IGNORECASE)
_NOT_BOOKED_RE = re.compile(
    r"vorgemerkt|pending|reverted|declined|storniert|abgelehnt|failed|cancel|nicht gebucht|in bearbeitung",
    re.IGNORECASE,
)


def _sign_indicator_column(headers, mapping, rows, column_index) -> str | None:
    """A column whose values are all S/H (or D/C, DR/CR) next to an unsigned
    amount column — found by its content when the header isn't known."""
    if not mapping.get("amount"):
        return None
    used = {v for v in mapping.values() if v}
    for header in headers:
        if header in used:
            continue
        index = column_index[header]
        values = {(cell_text(r[index]) or "").upper() for r in rows if index < len(r)} - {""}
        if values and values <= (_INDICATOR_NEGATIVE | _INDICATOR_POSITIVE) - {"-", "+"}:
            return header
    return None


def _apply_sign_rules(amount, row, column_index, indicator_header, mapping, bank_format, amount_minor, options):
    if indicator_header and mapping.get("amount"):
        index = column_index[indicator_header]
        marker = (cell_text(row[index]) if index < len(row) else None) or ""
        if marker.upper() in _INDICATOR_NEGATIVE:
            amount = -abs(amount)
        elif marker.upper() in _INDICATOR_POSITIVE:
            amount = abs(amount)
    if bank_format is not None and bank_format.fee_separate and mapping.get("fee"):
        index = column_index[mapping["fee"]]
        fee_raw = row[index] if index < len(row) else None
        if cell_text(fee_raw):
            amount -= abs(amount_minor(fee_raw))  # the fee is charged on top of the amount
    if options.invert_signs:
        amount = -amount
    return amount
