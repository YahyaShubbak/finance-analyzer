"""Column-aware reading of statements printed as a table (e.g. comdirect).

The text-based layouts see a booking as one string ("Lastschrift / ITZEHOER
VERS.VEREIN 25715710-004 KS PA 27 737,84 -737,84") and have to guess which
number is the amount. Here the table's header row says where each column is
— Buchungstag/Valuta, Vorgang, Auftraggeber/Empfänger, Buchungstext,
Ausgang/Eingang, ... — and every word is assigned to its column by position:
the amount comes from the amount column only, the payee from the payee
column, the counterparty's IBAN from the IBAN column, and SEPA references
are kept apart from the purpose text.

A booking is a block of rows: it starts with a row that has a date in the
date column and an amount in an amount column; the following rows (value
date, wrapped payee, references) belong to it until the next booking, a
balance line, page furniture or the end of the page.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.importers.pdf_layouts.base import PDFParsedLine

_LINE_TOLERANCE = 0.5      # same printed row: centers closer than half a word height
_AMOUNT_TOLERANCE = 25.0   # an amount belongs to a column if its right edge is this close
_ALIGNED = 3.0             # a real table prints a column's amounts flush (right edges this close)

# Column headings (lowercase, without spaces/hyphens/colons) -> column kind.
_HEADINGS: dict[str, set[str]] = {
    "date": {"buchungstag", "buchungsdatum", "datum", "buchung", "bookingdate", "date", "transaktionsdatum",
             "belegdatum", "umsatztag"},
    "value_date": {"valuta", "wertstellung", "wert", "valutadatum", "valuedate"},
    "type": {"vorgang", "buchungsart", "umsatzart", "art", "typ", "type", "transactiontype"},
    "party": {"auftraggeber/empfänger", "auftraggeber/empfaenger", "empfänger", "empfaenger", "auftraggeber",
              "zahlungsempfänger", "zahlungsempfaenger", "begünstigter", "beguenstigter", "name", "payee",
              "counterparty", "gegenpartei", "auftraggeber/zahlungsempfänger"},
    "purpose": {"buchungstext", "verwendungszweck", "beschreibung", "text", "details", "description",
                "umsatzbeschreibung", "buchungsdetails", "buchungsinformationen"},
    "reference": {"referenz", "reference", "kundenreferenz"},
    "iban": {"iban/bic", "iban", "bic", "kontonummer/iban"},
    "amount": {"betrag", "umsatz", "amount", "betrag(eur)", "betragineur", "umsatzineur", "eur"},
    "amount_out": {"ausgang", "zahlungsausgang", "soll", "belastung", "belastungen", "debit", "abgang", "paidout",
                   "moneyout", "ausgaben", "lastschriften"},
    "amount_in": {"eingang", "zahlungseingang", "haben", "gutschrift", "gutschriften", "credit", "zugang", "paidin",
                  "moneyin", "einnahmen"},
    "balance": {"saldo", "kontostand", "balance"},
}
_KIND_OF = {heading: kind for kind, headings in _HEADINGS.items() for heading in headings}
_AMOUNT_KINDS = {"amount", "amount_out", "amount_in"}
_TEXT_KINDS = {"date", "value_date", "type", "party", "purpose", "reference", "iban"}

_DATE_RE = re.compile(r"^\d{1,2}\.\d{1,2}\.(?:\d{2}|\d{4})?$")
_AMOUNT_RE = re.compile(
    r"^[+\-−]?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}[+\-]?$|^[+\-−]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}[+\-]?$"
)
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
# SEPA details that follow the purpose text in the same column.
_DETAIL_MARKERS = re.compile(
    r"^(?:end-to-end-ref|core\s*/\s*mandatsref|b2b\s*/\s*mandatsref|mandatsref|gläubiger-id|glaeubiger-id|"
    r"kundenreferenz|eref\+|mref\+|cred\+|svwz\+)", re.IGNORECASE)
# Lines that are part of the page, not of a booking.
_FURNITURE = re.compile(
    r"seite \d|kundennummer|eine marke der|ust-?id|amtsgericht|handelsregister|vorstand|aufsichtsrat|"
    r"sitz der|^\d{5} [a-zäöüß]|finanzreport nr|kontoauszug nr|^bic\b|^blz\b", re.IGNORECASE)
_OPENING = re.compile(r"^(?:alter (?:saldo|kontostand)|saldo alt|kontostand alt|anfangssaldo|saldo ?vortrag|"
                      r"opening balance|previous balance|balance brought forward)\b", re.IGNORECASE)
_CLOSING = re.compile(r"^(?:neuer (?:saldo|kontostand)|saldo neu|kontostand neu|endsaldo|schlusssaldo|"
                      r"closing balance|new balance|balance carried forward)\b", re.IGNORECASE)


@dataclass
class _Column:
    kind: str
    x0: float
    x1: float
    secondary: set[str] = field(default_factory=set)  # headings stacked below ("Valuta" under "Buchungstag")


@dataclass
class _Row:
    page: int
    y: float
    height: float
    words: list[tuple]  # sorted by x
    line_no: int = 0  # index of this row among the extracted text's lines (an empty page is one empty line)

    @property
    def text(self) -> str:
        return " ".join(w[4] for w in self.words)


@dataclass
class TableParse:
    lines: list[PDFParsedLine]
    balance_events: list[tuple[int, str, str]]   # (row index, "open" | "close", amount text)
    unreadable_rows: int


def _rows(page_no: int, words: list[tuple]) -> list[_Row]:
    rows: list[_Row] = []
    for word in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        center, height = (word[1] + word[3]) / 2, max(word[3] - word[1], 1.0)
        if rows and rows[-1].page == page_no and abs(center - rows[-1].y) <= height * _LINE_TOLERANCE:
            rows[-1].words.append(word)
        else:
            rows.append(_Row(page_no, center, height, [word]))
    for row in rows:
        row.words.sort(key=lambda w: w[0])
    return rows


def _heading(text: str) -> str | None:
    return _KIND_OF.get(re.sub(r"[\s\-:]", "", text).lower())


def _is_data_row(row: _Row) -> bool:
    return any(_DATE_RE.match(w[4]) or _AMOUNT_RE.match(w[4]) for w in row.words)


def _header_columns(rows: list[_Row], index: int) -> tuple[list[_Column], int] | None:
    """Columns defined by the header row at `index` (plus a stacked second
    header row and headings wrapped onto it). Returns (columns, rows used)."""
    row = rows[index]
    if _is_data_row(row):
        return None
    below = rows[index + 1] if index + 1 < len(rows) else None
    if below is not None and (below.page != row.page or below.y - row.y > 2.2 * row.height or _is_data_row(below)):
        below = None
    columns: list[_Column] = []
    used_below: set[int] = set()
    for word in row.words:
        text = word[4]
        # a heading wrapped inside its column ("Zahlungseinga" / "ng")
        if _heading(text) is None and below is not None:
            for k, other in enumerate(below.words):
                if abs(other[2] - word[2]) <= 4 or abs(other[0] - word[0]) <= 4:
                    if _heading(text + other[4]):
                        text += other[4]
                        used_below.add(k)
                        break
        kind = _heading(text)
        if kind:
            columns.append(_Column(kind, word[0], word[2]))
    # headings stacked in the second header row share a column with the one above
    rows_used = 1
    if below is not None:
        stacked = [(k, w, _heading(w[4])) for k, w in enumerate(below.words) if k not in used_below and _heading(w[4])]
        if stacked or used_below:
            rows_used = 2
        for _k, word, kind in stacked:
            owner = next((c for c in columns if abs(c.x0 - word[0]) <= 8 or abs(c.x1 - word[2]) <= 4), None)
            if owner is not None:
                owner.secondary.add(kind)
            else:
                columns.append(_Column(kind, word[0], word[2]))
    kinds = {c.kind for c in columns} | {k for c in columns for k in c.secondary}
    if "date" not in kinds or not kinds & _AMOUNT_KINDS or len(columns) < 3:
        return None
    columns.sort(key=lambda c: c.x0)
    return columns, rows_used


def _amount_column(word: tuple, columns: list[_Column]) -> _Column | None:
    if not _AMOUNT_RE.match(word[4]):
        return None
    candidates = [c for c in columns if c.kind in _AMOUNT_KINDS | {"balance"}]
    best = min(candidates, key=lambda c: abs(c.x1 - word[2]), default=None)
    if best is not None and abs(best.x1 - word[2]) <= _AMOUNT_TOLERANCE:
        return best
    return None


def _text_column(word: tuple, columns: list[_Column]) -> _Column | None:
    text_columns = [c for c in columns if c.kind in _TEXT_KINDS]
    owner = None
    for column in text_columns:
        if column.x0 <= word[0] + 4:
            owner = column
    return owner or (text_columns[0] if text_columns else None)


def _signed(word_text: str, column: _Column) -> str:
    """Unsigned amounts in a money-out / money-in column get that column's sign."""
    if re.match(r"^[+\-−]|.*[+\-]$", word_text):
        return word_text
    if column.kind == "amount_out" and "amount_in" not in column.secondary:
        return f"-{word_text}"
    if column.kind == "amount_in" and "amount_out" not in column.secondary:
        return f"+{word_text}"
    return word_text


def parse_table(pages: list[list[tuple]]) -> TableParse | None:
    rows: list[_Row] = []
    line_no = 0
    for page_no, words in enumerate(pages):
        page_rows = _rows(page_no, words)
        for row in page_rows:
            row.line_no = line_no
            line_no += 1
        line_no += 0 if page_rows else 1
        rows += page_rows
    columns: list[_Column] | None = None
    lines: list[PDFParsedLine] = []
    events: list[tuple[int, str, str]] = []
    unreadable = 0
    current: dict | None = None
    current_page = -1

    def finish():
        nonlocal current
        if current is not None:
            lines.append(_to_line(current))
            current = None

    alignment: list[tuple[int, float, float, float | None]] = []  # (column, heading x1, amount x1, date x0)
    index = 0
    while index < len(rows):
        row = rows[index]
        if row.page != current_page:
            finish()
            current_page = row.page
        header = _header_columns(rows, index)
        if header is not None:
            finish()
            columns, used = header
            index += used
            continue
        text = row.text
        if _OPENING.match(text) or _CLOSING.match(text):
            finish()
            amount = next((w[4] for w in reversed(row.words) if _AMOUNT_RE.match(w[4])), None)
            if amount:
                events.append((row.line_no, "open" if _OPENING.match(text) else "close", amount))
            index += 1
            continue
        if columns is None:
            index += 1
            continue

        cells: dict[str, list[str]] = {}
        amounts: list[tuple[str, _Column, float]] = []
        date_x0 = None
        for word in row.words:
            amount_column = _amount_column(word, columns)
            if amount_column is not None:
                if amount_column.kind != "balance":
                    amounts.append((_signed(word[4], amount_column), amount_column, word[2]))
                continue
            if date_x0 is None and _DATE_RE.match(word[4]):
                date_x0 = word[0]
            column = _text_column(word, columns)
            if column is not None:
                cells.setdefault(column.kind, []).append(word[4])
        date_cell = cells.get("date", [])
        starts = bool(amounts) and bool(date_cell) and _DATE_RE.match(date_cell[0])
        if not starts and _FURNITURE.search(text):
            finish()  # page footer / header: the booking above has ended
        elif starts:
            finish()
            amount_text, amount_column, amount_x1 = amounts[-1]
            current = {"row": row.line_no, "date": date_cell[0], "amount": amount_text, "rows": [cells]}
            alignment.append((id(amount_column), amount_column.x1, amount_x1, date_x0))
        elif current is not None:
            current["rows"].append(cells)
        elif date_cell and _DATE_RE.match(date_cell[0]):
            unreadable += 1  # a dated row with no amount in the amount column
        index += 1
    finish()
    if not lines or not _is_aligned(alignment):
        return None
    return TableParse(lines=lines, balance_events=events, unreadable_rows=unreadable)


def _is_aligned(alignment: list[tuple[int, float, float, float | None]]) -> bool:
    """Text that merely flows under a header row is not a table: in a real one
    each amount column is printed flush — under its heading, or at least all
    at the same edge — and the dates start at the same position."""
    by_column: dict[int, list[tuple[float, float]]] = {}
    for column, heading_x1, amount_x1, _date_x0 in alignment:
        by_column.setdefault(column, []).append((heading_x1, amount_x1))
    for entries in by_column.values():
        edges = [amount_x1 for _heading_x1, amount_x1 in entries]
        under_heading = all(abs(heading_x1 - amount_x1) <= _ALIGNED for heading_x1, amount_x1 in entries)
        flush = len(edges) >= 3 and max(edges) - min(edges) <= _ALIGNED
        if not (under_heading or flush):
            return False
    date_starts = [date_x0 for *_rest, date_x0 in alignment if date_x0 is not None]
    return not date_starts or max(date_starts) - min(date_starts) <= _ALIGNED


def _to_line(block: dict) -> PDFParsedLine:
    rows: list[dict[str, list[str]]] = block["rows"]

    def joined(kind: str, which: slice) -> str:
        return " ".join(" ".join(r.get(kind, [])) for r in rows[which]).strip()

    value_date = None
    if len(rows) > 1:
        second = rows[1].get("date", []) + rows[1].get("value_date", [])
        value_date = next((t for t in second if _DATE_RE.match(t)), None)
    if value_date is None:
        value_date = next((t for t in rows[0].get("value_date", []) if _DATE_RE.match(t)), None)

    booking_type = joined("type", slice(0, 2))
    party = joined("party", slice(0, 2))
    references = joined("type", slice(2, None)) + " " + joined("reference", slice(None))
    bank_lines = joined("party", slice(2, None)) + " " + joined("iban", slice(None))
    iban = next(iter(_IBAN_RE.findall(bank_lines)), None)

    purpose, details = [], []
    in_details = False
    for r in rows:
        line = " ".join(r.get("purpose", []))
        if not line:
            continue
        in_details = in_details or bool(_DETAIL_MARKERS.match(line))
        target = details if in_details else purpose
        if target and target[-1].endswith(":"):
            target[-1] = f"{target[-1]} {line}"  # "End-to-End-Ref.:" + its value on the next row
        else:
            target.append(line)
    details += [part for part in (references.strip(), bank_lines.strip()) if part]

    description = " ".join(part for part in (booking_type, party, " ".join(purpose)) if part)
    return PDFParsedLine(
        source_row_index=block["row"],
        date_text=block["date"],
        description=description or None,
        amount_text=block["amount"],
        value_date_text=value_date,
        details=details,
        counterparty=party or None,
        counterparty_iban=iban,
    )
