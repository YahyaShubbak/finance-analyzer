from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.db.models import DocumentType
from app.importers.parsing_utils import DATE_FORMATS
from app.services.import_staging import STAGING_ID_PATTERN


class ImportIssueRead(BaseModel):
    severity: str
    message: str
    row_index: int | None = None


class ParsedTransactionRead(BaseModel):
    source_row_index: int
    original_date_text: str | None
    original_description: str | None
    original_amount_text: str | None
    original_currency_text: str | None
    parsed_amount_minor: int | None
    parsed_date: str | None
    parsed_currency: str | None = None
    counterparty: str | None = None
    details: str | None = None  # the lines printed under it (purpose, reference, branch)
    # where it is printed: PDF {"page", "x0", "y0", "x1", "y1"}; spreadsheet {"row"}
    location: dict | None = None


class DuplicateMatchRead(BaseModel):
    transaction_id: int
    transaction_date: str
    merchant: str | None
    normalized_description: str
    amount_minor: int
    currency: str


class RowClassificationRead(BaseModel):
    source_row_index: int
    status: str  # "new" | "exact_duplicate" | "possible_duplicate"
    parsed_merchant: str | None
    parsed_category: str | None
    transaction_type: str | None = None
    needs_review: bool
    review_reason: str | None
    match: DuplicateMatchRead | None = None
    match_reason: str | None = None
    repeated_in_file: bool = False


_Coordinate = Annotated[float, Field(ge=-10_000, le=10_000, allow_inf_nan=False)]
_Text = Annotated[str, Field(max_length=200)]


class PdfTemplateIn(BaseModel):
    """How to read a PDF the built-in readers don't understand — taught in
    the import review (see app/importers/pdf_layouts/template.py)."""
    # x-range (left, right; PDF points) of each part of the example booking line
    columns: dict[Literal["date", "value_date", "text", "amount", "sign"], tuple[_Coordinate, _Coordinate]]
    sign_rule: Literal["as_printed", "unsigned_is_expense", "unsigned_is_income"] = "as_printed"
    ignore: list[_Text] = Field(default_factory=list, max_length=100)
    labels: dict[Literal["total", "opening", "closing"], _Text] = Field(default_factory=dict)
    document_type: Literal["credit_card_statement", "bank_statement"] = "bank_statement"


class ParseOptionsIn(BaseModel):
    """Choices from the column-mapping dialog; any field left out is
    auto-detected."""
    column_mapping: dict[str, str | None] | None = None
    header_row: int | None = Field(default=None, ge=0)
    date_format: Literal[DATE_FORMATS] | None = None  # type: ignore[valid-type]
    decimal_separator: Literal[",", "."] | None = None
    invert_signs: bool | None = None
    # a PDF reading template taught in the import review (see app/importers/pdf_layouts/template.py)
    pdf_template: PdfTemplateIn | None = None


class TotalCheckRead(BaseModel):
    """Do the bookings add up to what the document states itself?"""
    kind: str  # "balance": opening + bookings == closing; "statement_total": card purchases == statement amount
    ok: bool
    difference_minor: int


class ImportPreviewResponse(BaseModel):
    staging_id: str
    filename: str
    # None: the account was neither given nor recognized — the user chooses
    # one (reparse), and only then are duplicates classified.
    account_id: int | None
    account_name: str | None
    # How the account was recognized without asking (app.services.account_recognition)
    # "replaced": a known kind of file printing a new card number (a replaced card)
    account_recognized: Literal["iban", "history", "format", "replaced"] | None = None
    # Recognized account and nothing to look at: may be imported without confirmation.
    auto_import: bool = False
    # Open the import review by itself: a kind of file not checked yet, or something to look at.
    review_reasons: list[str] = []
    # The original, for the import review (see ParsedImport.page_count / layout_lines / source_rows).
    page_count: int = 0
    layout_lines: list[dict] = []
    source_rows: list[list[str]] = []
    document_type: DocumentType
    detected_columns: dict[str, str | None]
    detected_layout: str | None
    period_start: str | None
    period_end: str | None
    transaction_count: int
    transactions: list[ParsedTransactionRead]
    issues: list[ImportIssueRead]
    ambiguous: bool
    has_errors: bool
    statement_total_minor: int | None = None
    other_totals: dict[str, int] = {}
    total_check: TotalCheckRead | None = None

    # Detection results for the mapping dialog (CSV/XLSX only).
    available_columns: list[str] = []
    header_row_index: int | None = None
    date_format: str | None = None
    date_format_candidates: list[str] = []
    decimal_separator: str | None = None
    needs_decimal_separator: bool = False
    options: ParseOptionsIn = ParseOptionsIn()

    # Duplicate/review classification.
    new_count: int = 0
    exact_duplicate_count: int = 0
    possible_duplicate_count: int = 0
    needs_review_count: int = 0
    unusable_row_count: int = 0   # rows without a readable date/amount — kept as raw records only
    warning_count: int = 0
    row_classifications: list[RowClassificationRead] = []


class ReparseRequest(BaseModel):
    account_id: int | None = None  # None: not chosen yet (e.g. while teaching the reader in the review)
    options: ParseOptionsIn = ParseOptionsIn()


class RowDecision(BaseModel):
    source_row_index: int
    decision: Literal["skip", "keep"]


class ImportCommitRequest(BaseModel):
    staging_id: str = Field(pattern=STAGING_ID_PATTERN)
    account_id: int
    row_decisions: list[RowDecision] = []
    # Imported without the user looking at the preview: refused if, by now,
    # a row could be a duplicate (e.g. a file of the same month imported meanwhile).
    auto: bool = False
    # Checked in the import review: files of this kind go to this account
    # without asking from now on ("don't ask again for this bank/card").
    verified: bool = False


class ImportCommitResponse(BaseModel):
    import_id: int
    filename: str
    transactions_created: int
    duplicates_flagged: int
    rows_skipped: int = 0
    credit_card_statement_id: int | None = None
    # already imported bookings completed with details only this file has
    transactions_enriched: int = 0


class ImportRecordRead(BaseModel):
    id: int
    filename: str
    document_type: DocumentType
    account_id: int
    account_name: str
    imported_at: str
    period_start: str | None
    period_end: str | None
    status: str
    detected_transaction_count: int


class BulkImportRemovalRequest(BaseModel):
    import_ids: list[int] = Field(min_length=1, max_length=1000)


class BulkImportRemovalResponse(BaseModel):
    imports_removed: int
    transactions_removed: int


class ImportRemovalResponse(BaseModel):
    import_id: int
    filename: str
    transactions_removed: int
    raw_transactions_removed: int
    transfer_partners_reverted: int
    statements_removed: int
    reconciliations_recomputed: int
