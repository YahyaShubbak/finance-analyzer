"""PDF importer.

Extracts text locally via PyMuPDF, then asks every registered layout
parser (app.importers.pdf_layouts) for a confidence score and delegates
to the best match — never guesses which layout to use if no parser is
confident (or two are equally confident), and never silently imports
incorrect data.

Text is reconstructed line by line from word positions: statements are
tables, and PyMuPDF's plain text mode emits each table cell on its own
line, which would make "date description amount" rows unrecognizable.
"""
from __future__ import annotations

import hashlib
import re
from bisect import bisect_left, bisect_right

import pymupdf as fitz  # PyMuPDF (modern import name; `fitz` alias is deprecated upstream)

from app.db.models import DocumentType
from app.i18n import tr
from app.importers.base import BaseImporter, ImportIssue, ParsedImport, ParsedTransaction
from app.importers.currency import normalize_currency
from app.importers.parsing_utils import (
    AmountParseError,
    DateParseError,
    detect_date_format,
    parse_date,
    parse_date_flexible,
)
from app.importers.pdf_layouts import LAYOUT_REGISTRY
from app.importers.pdf_layouts.base import booked_amount_minor
from app.importers.pdf_layouts.patterns import BALANCE_LINE_RE, may_be_missed_booking, reference_date
from app.importers.pdf_layouts.points import extract_points

#: Words whose vertical centers differ by less than this fraction of the
#: word height are on the same printed line.
_LINE_TOLERANCE = 0.5

#: Below this confidence, no layout parser is trusted to have identified
#: the document correctly — we refuse to guess.
DETECTION_THRESHOLD = 0.3


class PDFImportError(Exception):
    pass


class PDFImporter(BaseImporter):
    def can_handle(self) -> bool:
        return self.file_path.suffix.lower() == ".pdf"

    def _extract(self) -> tuple[str, list[list[tuple]]]:
        try:
            doc = fitz.open(self.file_path)
        except Exception as exc:  # corrupt/unreadable PDF
            # (the error text names the staged file's full path — not for the user)
            raise PDFImportError(tr("Could not open the PDF — it may be damaged or not a PDF file.")) from exc

        try:
            if doc.needs_pass:
                raise PDFImportError(tr("This PDF is password-protected. Please save it without a password "
                                        "(e.g. print it to a new PDF) and import that file."))
            pages = [page.get_text("words") for page in doc]
        except PDFImportError:
            raise
        except Exception as exc:  # noqa: BLE001 — e.g. a damaged page
            raise PDFImportError(tr("Could not open the PDF — it may be damaged or not a PDF file.")) from exc
        finally:
            doc.close()
        # Statements that print money in and money out in two unsigned
        # columns: the column decides the direction (see _amount_columns).
        columns = _amount_columns(pages)
        pages_text = [_lines_from_words(words, columns) for words in pages]

        return "\n".join(pages_text), pages

    def parse(self) -> ParsedImport:
        raw_bytes = self.file_path.read_bytes()
        checksum = hashlib.sha256(raw_bytes).hexdigest()

        try:
            full_text, pages = self._extract()
        except PDFImportError as exc:
            return ParsedImport(
                filename=self.original_filename,
                file_checksum=checksum,
                document_type=DocumentType.UNKNOWN,
                detected_columns={},
                transactions=[],
                issues=[ImportIssue(severity="error", message=str(exc))],
                ambiguous=True,
            )

        if not full_text.strip():
            return ParsedImport(
                filename=self.original_filename,
                file_checksum=checksum,
                document_type=DocumentType.UNKNOWN,
                detected_columns={},
                transactions=[],
                issues=[ImportIssue(
                    severity="error",
                    message=tr("No extractable text found in this PDF. It may be a scanned "
                               "image — OCR is not enabled in V1. Please provide a text-based "
                               "PDF, or a CSV export instead."),
                )],
                ambiguous=True,
            )

        scores = sorted(((parser.detect(full_text), parser) for parser in LAYOUT_REGISTRY),
                        key=lambda pair: pair[0], reverse=True)
        best_score, best_parser = scores[0] if scores else (0.0, None)
        tied = len(scores) > 1 and scores[1][0] == best_score
        recognized = not (best_parser is None or best_score < DETECTION_THRESHOLD or tied)
        builtin = (best_parser.parse_pages(full_text, pages) if hasattr(best_parser, "parse_pages")
                   else best_parser.parse(full_text)) if recognized else None
        # the kind of file as the built-in readers see it — the same with or without a template
        signature_kind = f"{builtin.document_type.value}|{best_parser.name}" if builtin else "unknown|"

        template = self.options.pdf_template if self.options else None
        if template:
            from app.importers.pdf_layouts.template import parse_with_template

            result, layout_name = parse_with_template(template, full_text, pages), "user_template"
        elif not recognized:
            return ParsedImport(
                filename=self.original_filename,
                file_checksum=checksum,
                document_type=DocumentType.UNKNOWN,
                detected_columns={},
                transactions=[],
                issues=[ImportIssue(
                    severity="error",
                    message=tr("Could not confidently identify this document's layout "
                               "(bank statement vs. credit-card statement vs. unknown). "
                               "No transactions were imported. The original file is preserved "
                               "so you can inspect it, or a bank-specific parser can be added."),
                )],
                ambiguous=True,
                page_count=len(pages),
                layout_lines=_layout_lines(full_text, line_geometry(pages), set()),
                signature_kind=signature_kind,
            )
        else:
            result, layout_name = builtin, best_parser.name
        issues = [ImportIssue(severity="error", message=e) for e in result.errors]
        issues += [ImportIssue(severity="warning", message=w) for w in result.warnings]

        # One date format for the whole document (see parsing_utils).
        date_format, date_candidates = detect_date_format([line.date_text for line in result.lines if line.date_text])
        if date_format is None and len(date_candidates) > 1:
            issues.append(ImportIssue(
                severity="error",
                message=tr("The dates in this PDF could be read as day/month or month/day. "
                           "Please import a CSV export of this statement instead."),
            ))

        transactions: list[ParsedTransaction] = []
        for line in result.lines:
            ptx = ParsedTransaction(
                source_row_index=line.source_row_index,
                original_date_text=line.date_text,
                original_description=line.description,
                original_amount_text=line.amount_text,
                original_currency_text=line.currency_text,
            )
            if line.date_text:
                try:
                    parsed = parse_date(line.date_text, date_format) if date_format else parse_date_flexible(line.date_text)
                    ptx.parsed_date = parsed.isoformat()
                except DateParseError:
                    issues.append(ImportIssue(
                        severity="warning",
                        message=tr("Line {line}: could not parse date {date!r}.", line=line.source_row_index,
                                   date=line.date_text),
                        row_index=line.source_row_index,
                    ))
            ptx.parsed_currency = normalize_currency(line.currency_text) if line.currency_text else None
            if line.details:
                ptx.extra_fields["_details"] = " | ".join(line.details)
            if line.counterparty:
                ptx.counterparty = line.counterparty
                ptx.extra_fields["_counterparty"] = line.counterparty
            if line.counterparty_iban:
                ptx.counterparty_iban = line.counterparty_iban
            if line.value_date_text:
                try:
                    value_date = (parse_date(line.value_date_text, date_format) if date_format
                                  else parse_date_flexible(line.value_date_text))
                    ptx.extra_fields["_value_date"] = value_date.isoformat()
                except DateParseError:
                    pass
            if line.amount_text:
                try:
                    ptx.parsed_amount_minor = booked_amount_minor(
                        line.amount_text, result.document_type == DocumentType.CREDIT_CARD_STATEMENT,
                        line.credit_marker,
                    )
                except AmountParseError:
                    issues.append(ImportIssue(
                        severity="warning",
                        message=tr("Line {line}: could not parse amount {amount!r}.", line=line.source_row_index,
                                   amount=line.amount_text),
                        row_index=line.source_row_index,
                    ))
            transactions.append(ptx)

        ambiguous = len(transactions) == 0
        dates = sorted(t.parsed_date for t in transactions if t.parsed_date)
        geometry = line_geometry(pages)
        for ptx in transactions:
            box = geometry[ptx.source_row_index] if 0 <= ptx.source_row_index < len(geometry) else None
            if box:
                ptx.location = {k: v for k, v in box.items() if k != "words"}
        layout_lines = _layout_lines(full_text, geometry, {t.source_row_index for t in transactions})
        points = extract_points(full_text.splitlines(), [t.source_row_index for t in transactions],
                                reference_date(full_text, result.period_end))

        return ParsedImport(
            filename=self.original_filename,
            file_checksum=checksum,
            document_type=result.document_type,
            detected_columns={},
            transactions=transactions,
            issues=issues,
            # The statement's own period when printed, else the date range of its lines.
            period_start=result.period_start or (dates[0] if dates else None),
            period_end=result.period_end or (dates[-1] if dates else None),
            ambiguous=ambiguous,
            statement_total_minor=result.statement_total_minor,
            other_totals=result.other_totals,
            detected_layout=layout_name,
            total_check={"kind": "balance", **result.balance_check} if result.balance_check else None,
            page_count=len(pages),
            layout_lines=layout_lines,
            signature_kind=signature_kind,
            points=points.to_dict() if points.entries else None,
        )


# Column headings of statements with separate money-in / money-out columns,
# without spaces or hyphens ("Paid in" -> "paidin"). Headings are often
# wrapped inside the column ("Zahlungseinga" / "ng"), so vertically stacked
# fragments are joined before matching.
_MONEY_IN_HEADINGS = {
    "zahlungseingang", "zahlungseingänge", "eingang", "eingänge", "eingaenge", "haben", "gutschrift", "gutschriften",
    "einnahmen", "einzahlungen", "zugang", "zugänge", "credit", "credits", "paidin", "moneyin", "deposits",
}
_MONEY_OUT_HEADINGS = {
    "zahlungsausgang", "zahlungsausgänge", "ausgang", "ausgänge", "ausgaenge", "soll", "belastung", "belastungen",
    "lastschriften", "ausgaben", "auszahlungen", "abgang", "abgänge", "debit", "debits", "paidout", "moneyout",
    "withdrawals",
}
_UNSIGNED_AMOUNT_RE = re.compile(r"^(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}$|^(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}$")
_DATE_WORD_RE = re.compile(r"^\d{1,2}[./]\d{1,2}[./]?(?:\d{2,4})?$")
#: How far (points) an amount's right edge may be from its column heading's.
_COLUMN_TOLERANCE = 25.0


def _could_start_heading(text: str) -> bool:
    start = re.sub(r"[\s\-:]", "", text).lower()
    return bool(start) and any(h.startswith(start) for h in _MONEY_IN_HEADINGS | _MONEY_OUT_HEADINGS)


def _amount_columns(pages: list[list[tuple]]) -> tuple[float, float] | None:
    """Right edges (x) of the money-in and money-out column headings, if the
    statement has both on one heading row. Words on lines that hold a date
    or an amount are ignored, so "Gutschrift"/"Lastschrift" in booking texts
    never count as headings."""
    for words in pages:
        rows: dict[int, list[tuple]] = {}
        for w in words:
            rows.setdefault(round((w[1] + w[3]) / 2), []).append(w)
        busy_rows = {
            y for y, ws in rows.items()
            if any(_DATE_WORD_RE.match(w[4]) or _UNSIGNED_AMOUNT_RE.match(w[4].lstrip("+-−")) for w in ws)
        }
        candidates = sorted((w for y, ws in rows.items() if y not in busy_rows for w in ws), key=lambda c: c[1])
        tops = [c[1] for c in candidates]
        headings: list[tuple[str, float, float]] = []  # (normalized text, x1, top y)
        # only a word a heading can start with starts one (linear, not every word against every word)
        for w in (c for c in candidates if _could_start_heading(c[4])):
            text, bottom = w[4], w[3]
            # join fragments wrapped below this word in the same column
            i = bisect_left(tops, bottom - 2)
            while i < len(candidates) and candidates[i][1] - bottom <= (w[3] - w[1]) * 1.2:
                below = candidates[i]
                if below[1] - bottom >= -2 and below is not w and (abs(below[2] - w[2]) <= 4 or abs(below[0] - w[0]) <= 4):
                    text += below[4]
                    bottom = below[3]
                i += 1
            headings.append((text, w[2], w[1]))
            # two-word headings on one line ("Paid in")
            for right in candidates[bisect_left(tops, w[1] - 2):bisect_right(tops, w[1] + 2)]:
                if 0 < right[0] - w[2] <= 8:
                    headings.append((w[4] + right[4], right[2], w[1]))
        normalized = [(re.sub(r"[\s\-:]", "", text).lower(), x1, top) for text, x1, top in headings]
        money_in = [(x1, top) for text, x1, top in normalized if text in _MONEY_IN_HEADINGS]
        money_out = [(x1, top) for text, x1, top in normalized if text in _MONEY_OUT_HEADINGS]
        for in_x, in_top in money_in:
            for out_x, out_top in money_out:
                if abs(in_top - out_top) <= 15 and abs(in_x - out_x) > 2 * _COLUMN_TOLERANCE \
                        and _bookings_under(pages, (in_x, out_x)):
                    return in_x, out_x
    return None


def _bookings_under(pages: list[list[tuple]], columns: tuple[float, float]) -> bool:
    """The headings belong to the booking table only if the amounts of the
    booking rows (rows with a date) stand under them — a summary box at the
    top ("Gutschriften | Neue Belastungen") has its own amounts."""
    aligned = total = 0
    for words in pages:
        rows: dict[int, list[tuple]] = {}
        for w in words:
            rows.setdefault(round((w[1] + w[3]) / 2), []).append(w)
        for ws in rows.values():
            if not any(_DATE_WORD_RE.match(w[4]) for w in ws):
                continue
            for w in ws:
                if _UNSIGNED_AMOUNT_RE.match(w[4]):
                    total += 1
                    aligned += min(abs(w[2] - columns[0]), abs(w[2] - columns[1])) <= _COLUMN_TOLERANCE
    return total > 0 and aligned >= 0.5 * total


def _signed_by_column(word: tuple, columns: tuple[float, float] | None) -> str:
    text = word[4]
    if columns is None or not _UNSIGNED_AMOUNT_RE.match(text):
        return text
    in_x, out_x = columns
    to_in, to_out = abs(word[2] - in_x), abs(word[2] - out_x)
    if min(to_in, to_out) > _COLUMN_TOLERANCE:
        return text  # another column (e.g. the balance)
    return f"+{text}" if to_in < to_out else f"-{text}"


def _group_lines(words: list[tuple]) -> list[list[tuple]]:
    """The page's printed lines as word groups (left to right, top to bottom)."""
    # words: (x0, y0, x1, y1, text, block, line, word)
    words = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines: list[list[tuple]] = []
    current_center = None
    for word in words:
        center = (word[1] + word[3]) / 2
        height = max(word[3] - word[1], 1.0)
        if current_center is None or abs(center - current_center) > height * _LINE_TOLERANCE:
            lines.append([word])
            current_center = center
        else:
            lines[-1].append(word)
    return [sorted(line, key=lambda w: w[0]) for line in lines]


def _lines_from_words(words: list[tuple], columns: tuple[float, float] | None = None) -> str:
    if not words:
        return ""
    return "\n".join(" ".join(_signed_by_column(w, columns) for w in line) for line in _group_lines(words))


def line_geometry(pages: list[list[tuple]]) -> list[dict | None]:
    """Where each line of the extracted text (its index in splitlines()) is
    printed: {"page", "x0", "y0", "x1", "y1"} in PDF points, and its words
    ({"text", "x0", "x1"}, for teaching a template) — None for the empty
    line an empty page leaves."""
    boxes: list[dict | None] = []
    for page_no, words in enumerate(pages):
        if not words:
            boxes.append(None)
            continue
        for line in _group_lines(words):
            boxes.append({
                "page": page_no,
                "x0": round(min(w[0] for w in line), 1), "y0": round(min(w[1] for w in line), 1),
                "x1": round(max(w[2] for w in line), 1), "y1": round(max(w[3] for w in line), 1),
                "words": [{"text": w[4], "x0": round(w[0], 1), "x1": round(w[2], 1)} for w in line],
            })
    return boxes


# A statement's totals and balances (shown as such in the import review).
_TOTAL_LINE_RE = re.compile(
    r"^(?:statement total|total due|new balance|previous balance|neuer saldo|alter saldo|rechnungsbetrag|"
    r"zu zahlender betrag|gesamtbetrag|saldo des|summe|endsaldo|anfangssaldo|(?:alter|neuer) kontostand)\b",
    re.IGNORECASE,
)


def _layout_lines(full_text: str, geometry: list[dict | None], booking_rows: set[int]) -> list[dict]:
    """Every printed line with what the reading made of it — for the import
    review, where the original is shown next to the bookings. Lines right
    under a booking (value date, purpose, reference) belong to it ("detail")."""
    out: list[dict] = []
    last_booking: dict | None = None
    for index, (text, box) in enumerate(zip(full_text.splitlines(), geometry, strict=False)):
        if box is None or not text.strip():
            continue
        stripped = text.strip()
        if index in booking_rows:
            role = "booking"
        elif BALANCE_LINE_RE.match(stripped) or _TOTAL_LINE_RE.search(stripped):
            role = "balance"
        elif last_booking is not None and out and out[-1]["role"] in ("booking", "detail") \
                and box["page"] == last_booking["page"] and box["y0"] - out[-1]["y1"] < 6 \
                and index - last_booking["index"] <= 4:
            role = "detail"
        elif may_be_missed_booking(stripped):
            role = "unreadable"  # starts with a date and holds an amount, yet no booking was read
        else:
            role = "text"
        line = {"index": index, "text": stripped, "role": role, **box}
        if role == "booking":
            last_booking = line
        out.append(line)
    return out
