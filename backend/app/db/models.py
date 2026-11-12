"""Persistent database schema.

Design principles (see project spec sections 6, 15, 18, 45):

* Money is ALWAYS stored as integer minor units (e.g. cents) — never float.
* Raw imported data (RawTransaction) is immutable and never overwritten.
* Normalized data (Transaction) is derived from raw data but can be
  recomputed; user corrections are layered on top and are never silently
  clobbered by re-import or re-normalization.
* Every Transaction traces back to exactly one RawTransaction, which
  traces back to exactly one ImportRecord (source file).
"""
import enum
from datetime import UTC, date, datetime
from typing import List, Optional

from sqlalchemy import Column, ForeignKey, Integer
from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite has no native timezone-aware type)."""
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AccountType(str, enum.Enum):
    CHECKING = "checking"
    SAVINGS = "savings"
    CREDIT_CARD = "credit_card"
    OTHER = "other"


class DocumentType(str, enum.Enum):
    BANK_STATEMENT = "bank_statement"
    CREDIT_CARD_STATEMENT = "credit_card_statement"
    UNKNOWN = "unknown"


class ImportStatus(str, enum.Enum):
    PENDING = "pending"          # preview generated, not yet committed
    IMPORTED = "imported"
    FAILED = "failed"
    DUPLICATE = "duplicate"      # entire file already imported before


class TransactionType(str, enum.Enum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"
    UNKNOWN = "unknown"


class ReconciliationStatus(str, enum.Enum):
    RECONCILED = "reconciled"
    MISMATCH = "mismatch"
    UNRESOLVED = "unresolved"
    PENDING = "pending"          # statement imported, bank debit not yet matched


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

class Account(SQLModel, table=True):
    __tablename__ = "accounts"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    account_type: AccountType
    currency: str = Field(default="EUR", max_length=8)
    created_at: datetime = Field(default_factory=utcnow)
    is_archived: bool = False

    # Optional, normalized (uppercase, no spaces). Lets transfer detection
    # recognize a transaction whose counterparty is one of the user's own
    # accounts, which is far more reliable than amount/date alone.
    iban: Optional[str] = Field(default=None, max_length=34)

    # Optional, user-entered — deliberately separate from anything derived
    # from imported transactions (spec: never conflate the two). When set,
    # the "current balance" shown to the user is this value plus the sum
    # of transactions dated on/after opening_balance_date; the plain sum
    # of ALL imported transactions is always shown too, unaffected by this.
    opening_balance_minor: Optional[int] = None
    opening_balance_date: Optional[date] = None

    transactions: List["Transaction"] = Relationship(back_populates="account")
    imports: List["ImportRecord"] = Relationship(back_populates="account")


# ---------------------------------------------------------------------------
# Imports (source files)
# ---------------------------------------------------------------------------

class ImportRecord(SQLModel, table=True):
    __tablename__ = "imports"
    # An id is never given twice: "Undo"/"Remove" name an import by its id,
    # and a window still showing a removed import must not hit a newer one
    # that got the same id (SQLite otherwise reuses the highest id).
    __table_args__ = {"sqlite_autoincrement": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str
    stored_path: str                      # relative path under imports/
    file_checksum: str = Field(index=True)  # sha256 — detects identical re-uploads
    document_type: DocumentType = DocumentType.UNKNOWN
    account_id: Optional[int] = Field(default=None, foreign_key="accounts.id")

    imported_at: datetime = Field(default_factory=utcnow)
    period_start: Optional[date] = None
    period_end: Optional[date] = None

    status: ImportStatus = ImportStatus.PENDING
    detected_transaction_count: int = 0
    error_message: Optional[str] = None

    # What kind of file this was, to recognize the account of the next one
    # (app.services.account_recognition): a hash of its format, and as JSON
    # the account identifiers it printed, the parse options and the
    # warnings accepted for it.
    source_key: Optional[str] = Field(default=None, index=True, max_length=64)
    source_info_json: Optional[str] = None

    account: Optional[Account] = Relationship(back_populates="imports")
    raw_transactions: List["RawTransaction"] = Relationship(back_populates="import_record")


# ---------------------------------------------------------------------------
# Raw (immutable, as-imported) transactions
# ---------------------------------------------------------------------------

class RawTransaction(SQLModel, table=True):
    __tablename__ = "raw_transactions"

    id: Optional[int] = Field(default=None, primary_key=True)
    import_id: int = Field(foreign_key="imports.id", index=True)
    source_row_index: int

    original_date_text: Optional[str] = None
    original_description: Optional[str] = None
    original_amount_text: Optional[str] = None
    original_currency_text: Optional[str] = None
    extra_fields_json: Optional[str] = None  # any other columns, as JSON, for traceability

    # A row that was not made a booking because it is one already there
    # (imported from another file before, see commit_parsed_import): that
    # booking. A card statement finds its purchases through it, the booking
    # its place, and it takes the booking over when the other file is removed.
    # (use_alter: transactions refer to their raw row, too — this reference
    # is the one left out when the tables are put in order.)
    duplicate_of_transaction_id: Optional[int] = Field(default=None, sa_column=Column(
        Integer,
        ForeignKey("transactions.id", use_alter=True, name="fk_raw_transactions_duplicate_of_transaction_id"),
        nullable=True, index=True,
    ))
    # The user imported this row as a booking of its own although it looked
    # like one already there: never merged with that one later (twin_merge).
    kept_by_user: bool = False

    import_record: Optional[ImportRecord] = Relationship(back_populates="raw_transactions")
    # (the booking made from this row — not the one it may point at above)
    transaction: Optional["Transaction"] = Relationship(
        back_populates="raw_transaction",
        sa_relationship_kwargs={"foreign_keys": "[Transaction.raw_transaction_id]"},
    )


# ---------------------------------------------------------------------------
# Normalized transactions
# ---------------------------------------------------------------------------

class Transaction(SQLModel, table=True):
    __tablename__ = "transactions"

    id: Optional[int] = Field(default=None, primary_key=True)
    raw_transaction_id: int = Field(foreign_key="raw_transactions.id", unique=True)
    account_id: int = Field(foreign_key="accounts.id", index=True)

    transaction_date: date = Field(index=True)
    value_date: Optional[date] = None

    normalized_description: str
    merchant: Optional[str] = Field(default=None, index=True)
    category: Optional[str] = Field(default=None, index=True)

    amount_minor: int          # signed integer minor units (e.g. cents)
    currency: str = Field(default="EUR", max_length=8)

    transaction_type: TransactionType = TransactionType.UNKNOWN

    duplicate_fingerprint: str = Field(index=True)
    is_duplicate: bool = False
    duplicate_of_id: Optional[int] = Field(default=None, foreign_key="transactions.id")

    # A transfer is money moving between the user's own accounts; it is
    # excluded from income/expense totals. Exactly one of the two fields
    # below says WHY a transaction is a transfer when it was set
    # automatically: paired with its counterpart on another account
    # (transfer detection), or settling a credit-card statement
    # (reconciliation). Neither set + is_transfer=True means the user
    # marked it manually.
    is_transfer: bool = False
    transfer_pair_id: Optional[int] = Field(default=None, foreign_key="transactions.id")
    settles_statement_id: Optional[int] = Field(
        default=None, foreign_key="credit_card_statements.id", index=True
    )

    # Where the payment took place, as far as the statement says (see
    # app.normalization.location): ISO country code and town, or an online
    # purchase. Worked out again when location_version is behind
    # LOCATION_VERSION.
    country: Optional[str] = Field(default=None, max_length=2, index=True)
    city: Optional[str] = Field(default=None, max_length=80)
    online: bool = False
    location_version: int = 0

    needs_review: bool = False
    review_reason: Optional[str] = None  # short, explainable reason (e.g. "Category could not be confidently determined")

    notes: Optional[str] = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    account: Optional[Account] = Relationship(back_populates="transactions")
    raw_transaction: Optional[RawTransaction] = Relationship(
        back_populates="transaction",
        sa_relationship_kwargs={"foreign_keys": "[Transaction.raw_transaction_id]"},
    )
    corrections: List["UserCorrection"] = Relationship(back_populates="transaction")


# ---------------------------------------------------------------------------
# User corrections (audit trail — never silently overwritten)
# ---------------------------------------------------------------------------

class UserCorrection(SQLModel, table=True):
    __tablename__ = "user_corrections"

    id: Optional[int] = Field(default=None, primary_key=True)
    transaction_id: int = Field(foreign_key="transactions.id", index=True)
    field: str                 # e.g. "category", "merchant", "transaction_type"
    old_value: Optional[str] = None
    new_value: str
    corrected_at: datetime = Field(default_factory=utcnow)

    transaction: Optional[Transaction] = Relationship(back_populates="corrections")


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

class CustomCategory(SQLModel, table=True):
    """A category the user created ("Darlehen", "Schulden"), next to the
    built-in ones (app.normalization.category.BUILT_IN_CATEGORIES).
    Transactions, rules and budgets refer to categories by name."""
    __tablename__ = "custom_categories"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, max_length=40)
    created_at: datetime = Field(default_factory=utcnow)


class Budget(SQLModel, table=True):
    """A recurring monthly spending target for one category (V1: no
    date-ranged or non-monthly budgets — matches the common "Groceries:
    400/month" mental model). One row per category, enforced by the
    unique index; upsert-by-category semantics live in budget_service."""
    __tablename__ = "budgets"

    id: Optional[int] = Field(default=None, primary_key=True)
    category: str = Field(index=True, unique=True)
    amount_minor: int
    currency: str = Field(default="EUR", max_length=8)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Merchant / category rule tables (V1 deterministic normalization)
# ---------------------------------------------------------------------------

class MerchantRule(SQLModel, table=True):
    __tablename__ = "merchant_rules"

    id: Optional[int] = Field(default=None, primary_key=True)
    pattern: str = Field(index=True)          # substring or regex, matched against original_description
    is_regex: bool = False
    normalized_merchant: str
    is_user_defined: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class CategoryRule(SQLModel, table=True):
    __tablename__ = "category_rules"

    id: Optional[int] = Field(default=None, primary_key=True)
    pattern: str = Field(index=True)          # matched against merchant or description
    is_regex: bool = False
    match_field: str = "merchant"             # "merchant" | "description"
    category: str
    priority: int = 100                        # lower = evaluated first
    amount_sign: str = "any"                   # "any" | "positive" | "negative" — e.g. "Salary" only for money in
    is_user_defined: bool = False
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Credit-card reconciliation
# ---------------------------------------------------------------------------

class CreditCardStatement(SQLModel, table=True):
    __tablename__ = "credit_card_statements"

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="accounts.id", index=True)
    import_id: int = Field(foreign_key="imports.id")

    statement_period_start: Optional[date] = None
    statement_period_end: Optional[date] = None
    statement_total_minor: Optional[int] = None
    other_totals_json: Optional[str] = None  # e.g. {"fee": 500, "interest": 1200}, from the parsed PDF
    currency: str = Field(default="EUR", max_length=8)

    created_at: datetime = Field(default_factory=utcnow)

    reconciliation: Optional["Reconciliation"] = Relationship(back_populates="statement")


class Reconciliation(SQLModel, table=True):
    __tablename__ = "reconciliations"

    id: Optional[int] = Field(default=None, primary_key=True)
    statement_id: int = Field(foreign_key="credit_card_statements.id", unique=True)

    transaction_total_minor: int
    statement_total_minor: Optional[int] = None
    bank_debit_transaction_id: Optional[int] = Field(default=None, foreign_key="transactions.id")
    bank_debit_amount_minor: Optional[int] = None

    # Both discrepancies are tracked separately since they have different
    # causes (spec sections 20-21): transactions-vs-statement (e.g. a
    # missing/duplicate line item) vs. statement-vs-bank-debit (e.g. a
    # partial payment or a fee applied at settlement).
    diff_transactions_vs_statement_minor: Optional[int] = None
    diff_statement_vs_bank_minor: Optional[int] = None
    difference_minor: Optional[int] = None  # the primary/headline difference shown in the UI

    status: ReconciliationStatus = ReconciliationStatus.PENDING
    explanation_tags_json: Optional[str] = None   # JSON list, e.g. ["fee","refund"] — ENGINE-COMPUTED, never user-edited
    resolved_by_user: bool = False
    resolution_notes: Optional[str] = None
    user_resolution_tags_json: Optional[str] = None  # JSON list — user's own annotation, kept separate from computed tags

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    statement: Optional[CreditCardStatement] = Relationship(back_populates="reconciliation")


# ---------------------------------------------------------------------------
# Bonus points (miles, ...) printed on card statements
# ---------------------------------------------------------------------------

class PointsProgram(SQLModel, table=True):
    """A bonus program as statements name it ("Shop Punkte", "PARTNER Punkte")."""
    __tablename__ = "points_programs"

    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(max_length=80, unique=True)  # "SHOP|PUNKTE" (app/importers/pdf_layouts/points.py)
    name: str = Field(max_length=80)
    unit: str = Field(default="Punkte", max_length=20)
    # what 100 points are worth, in cents (100: one point is one cent)
    value_per_100: int = 100
    value_set_by_user: bool = False  # then a statement's conversion doesn't overwrite it
    created_at: datetime = Field(default_factory=utcnow)


class PointsEntry(SQLModel, table=True):
    """Points earned by a booking, redeemed, or a statement's stated balance."""
    __tablename__ = "points_entries"

    id: Optional[int] = Field(default=None, primary_key=True)
    program_id: int = Field(foreign_key="points_programs.id", index=True)
    import_id: int = Field(foreign_key="imports.id", index=True)
    # the booking that earned them; no foreign key: the booking may be
    # removed with another file while this statement stays
    transaction_id: Optional[int] = Field(default=None, index=True)
    entry_date: date = Field(index=True)
    points: int  # signed
    kind: str = Field(max_length=12)  # "earned" | "redeemed" | "balance"
    value_minor: Optional[int] = None  # a redemption's value in cents, as printed
    note: Optional[str] = Field(default=None, max_length=80)
