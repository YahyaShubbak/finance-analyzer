"""Importer abstraction.

Every concrete importer (CSVImporter, XLSXImporter, PDFImporter) implements
`parse()` and returns a ParsedImport, which is a preview/staging structure
— nothing is written to the database until the caller explicitly commits
it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.db.models import DocumentType


@dataclass
class ParseOptions:
    """User choices from the import dialog, overriding auto-detection.
    Persisted next to the staged file so preview and commit always parse
    the file identically."""

    column_mapping: dict[str, str | None] | None = None   # logical field -> header
    header_row: int | None = None                         # 0-based row index
    date_format: str | None = None                        # strptime format, e.g. "%d/%m/%Y"
    decimal_separator: str | None = None                  # "," or "."
    invert_signs: bool | None = None                       # e.g. a card export listing purchases as positive
    pdf_template: dict | None = None                       # taught in the import review (pdf_layouts/template.py)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> ParseOptions:
        data = data or {}
        return cls(**{k: data.get(k) for k in cls.__dataclass_fields__})


@dataclass
class ParsedTransaction:
    """One transaction as detected from a source file, before DB persistence."""

    source_row_index: int
    original_date_text: str | None
    original_description: str | None
    original_amount_text: str | None
    original_currency_text: str | None = None
    extra_fields: dict = field(default_factory=dict)

    # Best-effort normalized values, filled in during parsing when possible.
    # These are *proposals* — normalization services may refine them further.
    parsed_amount_minor: int | None = None
    parsed_date: str | None = None  # ISO date string
    parsed_currency: str | None = None  # ISO 4217, None = use the account's currency
    counterparty: str | None = None
    counterparty_iban: str | None = None
    # Where it is printed in a PDF: {"page", "x0", "y0", "x1", "y1"} (points);
    # in a spreadsheet: {"row": index into ParsedImport.source_rows}.
    location: dict | None = None


@dataclass
class ImportIssue:
    """A non-fatal warning or a fatal error encountered while parsing."""

    severity: str  # "warning" | "error"
    message: str
    row_index: int | None = None


@dataclass
class ParsedImport:
    """Full result of parsing a source file — the import preview payload."""

    filename: str
    file_checksum: str
    document_type: DocumentType
    detected_columns: dict[str, str | None]  # logical field -> source column name
    transactions: list[ParsedTransaction]
    issues: list[ImportIssue] = field(default_factory=list)
    period_start: str | None = None
    period_end: str | None = None
    ambiguous: bool = False  # True => caller must show mapping UI before commit

    # Statement-level totals — only populated by statement-style importers
    # (currently PDF). Used by the reconciliation engine; left as None for
    # CSV imports where no independently-declared total exists.
    statement_total_minor: int | None = None
    other_totals: dict[str, int] = field(default_factory=dict)  # e.g. {"fee": 500, "interest": 1200}
    detected_layout: str | None = None  # name of the layout parser / bank format that matched
    # Whether the bookings add up to what the document itself states:
    # {"kind": "balance" | "statement_total", "ok": bool, "difference_minor": int}
    total_check: dict | None = None

    # Tabular (CSV/XLSX) detection results, shown in the mapping dialog.
    available_columns: list[str] = field(default_factory=list)
    header_row_index: int | None = None
    date_format: str | None = None
    date_format_candidates: list[str] = field(default_factory=list)
    decimal_separator: str | None = None
    needs_decimal_separator: bool = False

    # For checking the reading against the original (import review):
    # PDF: number of pages and every printed line with its role
    # ("booking" | "unreadable" | "balance" | "text"); spreadsheet: its rows.
    page_count: int = 0
    layout_lines: list[dict] = field(default_factory=list)
    # What kind of file this is, independent of any template the user taught
    # (so the next file of the kind is recognized before its template is applied).
    signature_kind: str | None = None
    source_rows: list[list[str]] = field(default_factory=list)
    # Bonus points printed on a card statement (app/importers/pdf_layouts/points.py: PointsParsed.to_dict())
    points: dict | None = None

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    @property
    def unusable_row_count(self) -> int:
        """Rows that will be kept as raw records only (no date or amount)."""
        return sum(1 for t in self.transactions if t.parsed_date is None or t.parsed_amount_minor is None)


class BaseImporter(ABC):
    """Common interface all file importers must implement."""

    def __init__(self, file_path: Path, original_filename: str | None = None, options: ParseOptions | None = None):
        self.file_path = Path(file_path)
        self.original_filename = original_filename or self.file_path.name
        self.options = options or ParseOptions()

    @abstractmethod
    def can_handle(self) -> bool:
        """Cheap check: does this look like a file this importer can parse?"""

    @abstractmethod
    def parse(self) -> ParsedImport:
        """Parse the file and return a preview, without touching the database."""
