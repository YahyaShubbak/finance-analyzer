"""Pluggable PDF "layout" parsers.

A layout parser knows how to interpret the *text content* of one specific
kind of statement (e.g. "generic bank statement", "generic credit-card
statement", and later "Deutsche Bank checking account", "Amex statement",
etc). The PDFImporter itself never hard-codes a bank-specific layout — it
just extracts text with PyMuPDF and asks each registered layout parser
"can you confidently parse this?", then delegates to the best match.

Adding support for a real bank/card issuer later means writing one new
class here (registered in the LAYOUT_REGISTRY) — the core database,
reconciliation engine, and GUI never need to change (spec section 9).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.db.models import DocumentType
from app.importers.parsing_utils import has_debit_credit_marker, parse_amount_to_minor_units


def booked_amount_minor(amount_text: str, card_statement: bool, credit_marker: bool = False) -> int:
    """A statement line's amount in the app's sign (money out negative) —
    the one reading for the importer and for a statement checking itself
    against its balances. Card statements list purchases as plain positive
    numbers and credits negative, so plain signs are turned round there; an
    explicit marker ("45,00 S", "300.00 CR") already states the direction.
    A credit marked below the line is money in. Raises AmountParseError."""
    minor = parse_amount_to_minor_units(amount_text)
    if card_statement and not has_debit_credit_marker(amount_text):
        minor = -minor
    return abs(minor) if credit_marker else minor


@dataclass
class PDFParsedLine:
    """One transaction line as detected in the PDF text."""

    source_row_index: int
    date_text: str | None
    description: str | None
    amount_text: str | None
    currency_text: str | None = None
    value_date_text: str | None = None
    details: list[str] = field(default_factory=list)  # continuation lines (references, purpose text)
    # A credit marked on the line(s) BELOW the booking, as American Express
    # does ("GUTSCHRIFT" under an otherwise unsigned amount).
    credit_marker: bool = False
    # The other reading of a line ending in two amounts ("text 12,34 -56,78"):
    # (description, amount_text) — tried when the statement's balances don't add up.
    alternative: tuple[str, str] | None = None
    # Read from their own columns by the table reader (pdf_layouts.table).
    counterparty: str | None = None
    counterparty_iban: str | None = None


@dataclass
class PDFParseResult:
    document_type: DocumentType
    lines: list[PDFParsedLine]
    period_start: str | None = None
    period_end: str | None = None
    statement_total_minor: int | None = None
    other_totals: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # the document must not be imported as is
    # Opening balance + bookings == closing balance? {"ok", "difference_minor"}; None when the
    # statement prints no usable balances.
    balance_check: dict | None = None


class BasePDFLayoutParser(ABC):
    """One concrete statement layout. Subclass per bank/issuer format."""

    #: unique, stable identifier used in diagnostics and tests
    name: str = "base"

    @abstractmethod
    def detect(self, full_text: str) -> float:
        """Return a confidence score in [0.0, 1.0] that this parser can
        correctly handle the given document text. 0.0 means "definitely not
        my format". Detection must be conservative — a false-positive match
        risks silently importing incorrect financial data (spec section 43).
        """

    @abstractmethod
    def parse(self, full_text: str) -> PDFParseResult:
        """Parse the document text. Only called after detect() returned a
        confidence above the selection threshold."""
