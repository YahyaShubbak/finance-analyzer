"""Orchestrates the full import pipeline:

    IMPORT -> RAW DATA -> NORMALIZATION -> DATABASE

Nothing is committed to `transactions`/`raw_transactions` until
`commit_parsed_import` is called explicitly — `parse_file` alone only
produces a preview.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from sqlmodel import Session, select

from app.db.models import (
    Account,
    AccountType,
    CreditCardStatement,
    DocumentType,
    ImportRecord,
    ImportStatus,
    RawTransaction,
    Transaction,
    TransactionType,
    UserCorrection,
)
from app.i18n import format_date, tr
from app.importers.base import ParsedImport, ParseOptions
from app.importers.csv_importer import CSVImporter
from app.importers.pdf_importer import PDFImporter
from app.importers.xlsx_importer import XLSXImporter
from app.normalization.category import UNSORTED_CATEGORIES
from app.normalization.review import compute_review_status
from app.services.duplicate_preview_service import classify_import_rows
from app.services.location_service import refresh_locations
from app.services.points_service import store_points

logger = logging.getLogger("finance")


class ImportServiceError(Exception):
    pass


def find_existing_import_by_checksum(session: Session, checksum: str) -> ImportRecord | None:
    stmt = select(ImportRecord).where(
        ImportRecord.file_checksum == checksum,
        ImportRecord.status == ImportStatus.IMPORTED,
    )
    return session.exec(stmt).first()


def build_importer_for(path: Path, original_filename: str | None = None, options: ParseOptions | None = None):
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return CSVImporter(path, original_filename, options)
    if suffix == ".pdf":
        return PDFImporter(path, original_filename, options)
    if suffix == ".xlsx":
        return XLSXImporter(path, original_filename, options)
    raise ImportServiceError(tr("No importer available for file type: {suffix}", suffix=suffix))


def parse_file(path: Path, original_filename: str | None = None, options: ParseOptions | None = None) -> ParsedImport:
    """Produce a preview without touching the database.

    A reader that stumbles over an unusual file (anything it doesn't report
    itself as an issue of the preview) raises ImportServiceError: the user
    is told the file could not be read, the cause goes to the log."""
    importer = build_importer_for(path, original_filename, options)
    if not importer.can_handle():
        raise ImportServiceError(tr("Importer cannot handle file: {path}", path=path))
    try:
        return importer.parse()
    except Exception as exc:  # noqa: BLE001 — whatever a reader didn't foresee
        logger.exception("Could not read %s", original_filename or path.name)
        raise ImportServiceError(tr(
            "This file could not be read: the reader ran into a problem it doesn't know ({error}). "
            "Nothing was imported.", error=type(exc).__name__)) from exc


def statement_already_imported(session: Session, parsed: ParsedImport, account: Account) -> str | None:
    """A card statement for this account with the same period and amount is
    already there — e.g. the same statement downloaded again (other bytes,
    same content). Importing it would add a second, empty statement."""
    if parsed.document_type != DocumentType.CREDIT_CARD_STATEMENT or not (parsed.period_start and parsed.period_end):
        return None
    same = session.exec(select(CreditCardStatement).where(
        CreditCardStatement.account_id == account.id,
        CreditCardStatement.statement_period_start == date.fromisoformat(parsed.period_start),
        CreditCardStatement.statement_period_end == date.fromisoformat(parsed.period_end),
        CreditCardStatement.statement_total_minor == parsed.statement_total_minor,
    )).first()
    if same is None:
        return None
    record = session.get(ImportRecord, same.import_id)
    return tr("This statement is already imported (from {file}).", file=record.filename if record else "?")


def document_account_mismatch(parsed: ParsedImport, account: Account) -> str | None:
    """A credit-card statement on a bank account would get every sign wrong
    (card statements list purchases as positive numbers) and create a
    statement on the wrong kind of account, so it is refused."""
    if parsed.document_type == DocumentType.CREDIT_CARD_STATEMENT and account.account_type != AccountType.CREDIT_CARD:
        return tr("This file looks like a credit-card statement, but '{account}' is not a credit-card "
                  "account. Choose the credit-card account (or create one) for this file.", account=account.name)
    return None


def document_account_warning(parsed: ParsedImport, account: Account) -> str | None:
    """A bank-statement PDF on a credit-card account is often the wrong file
    — but card accounts with an IBAN get exactly such statements, and the
    signs are read correctly either way. So it is a warning to confirm, not
    a refusal."""
    if parsed.document_type == DocumentType.BANK_STATEMENT and account.account_type == AccountType.CREDIT_CARD \
            and parsed.detected_layout and parsed.detected_layout.startswith("generic_bank_statement"):
        return tr("This PDF looks like an account statement, but '{account}' is a credit-card account. "
                  "That is fine for a card account with its own IBAN — otherwise choose the bank account.",
                  account=account.name)
    return None


def purchases_listed_as_positive(parsed: ParsedImport, account: Account) -> bool:
    """Card exports disagree on signs: many list purchases as positive
    numbers (the issuer's view). In this app a purchase is negative, so a
    card spreadsheet that is mostly positive was exported the other way
    round — otherwise every purchase would be imported as a refund."""
    if account.account_type != AccountType.CREDIT_CARD or not parsed.available_columns:
        return False
    amounts = [t.parsed_amount_minor for t in parsed.transactions if t.parsed_amount_minor]
    # The clearest sign: how the payment onto the card ("Zahlung erhalten, besten Dank", a booking
    # of type "Einzahlung") is shown — as money out, the file is the other way round; as money in,
    # it already is the app's way (even in a month with more payments than purchases).
    payments = [t.parsed_amount_minor for t in parsed.transactions if t.parsed_amount_minor and _PAYMENT_RECEIVED_RE.search(
        " ".join(filter(None, [t.original_description, (t.extra_fields or {}).get("_booking_text")])))]
    if any(a < 0 for a in payments):
        return True
    if payments:
        return False
    return len(amounts) >= 3 and sum(1 for a in amounts if a > 0) / len(amounts) >= 0.6


_PAYMENT_RECEIVED_RE = re.compile(
    r"zahlung[\w/ .-]{0,30}erhalten|payment[\w/ .-]{0,20}received|thank you for your payment|besten dank|"
    r"ihre zahlung|\beinzahlung\b",
    re.IGNORECASE,
)


@dataclass
class CommitResult:
    import_record: ImportRecord
    transactions_created: int
    duplicates_flagged: int
    rows_skipped: int = 0
    credit_card_statement: CreditCardStatement | None = None
    transactions_enriched: int = 0


# Information some sources carry and others don't (a bank's spreadsheet
# export has the card network's merchant category and the booking type;
# its PDF statement doesn't).
_ENRICHING_FIELDS = ("_merchant_category", "_booking_text", "_counterparty_iban", "_details")
_UNCLASSIFIED = {None, *UNSORTED_CATEGORIES}


def _enrich_existing(session: Session, existing_id: int, ptx, c) -> bool:
    """The same booking was imported before from another source. Fill in
    what that source lacked — never anything the user corrected by hand,
    and never a transfer pairing or statement payment."""
    existing = session.get(Transaction, existing_id)
    if existing is None or existing.raw_transaction is None:
        return False
    raw = existing.raw_transaction
    corrected = set(session.exec(select(UserCorrection.field).where(UserCorrection.transaction_id == existing.id)).all())
    changed = False

    extra = json.loads(raw.extra_fields_json) if raw.extra_fields_json else {}
    for key in _ENRICHING_FIELDS:
        value = (ptx.extra_fields or {}).get(key) if key != "_counterparty_iban" else ptx.counterparty_iban
        if value and not extra.get(key):
            extra[key] = value
            changed = True
    if changed:
        raw.extra_fields_json = json.dumps(extra, ensure_ascii=False)
        session.add(raw)

    if (c.transaction_type == TransactionType.TRANSFER and existing.transaction_type != TransactionType.TRANSFER
            and "transaction_type" not in corrected and existing.transfer_pair_id is None
            and existing.settles_statement_id is None):
        existing.transaction_type = TransactionType.TRANSFER
        existing.is_transfer = True
        if "category" not in corrected:
            existing.category = "Transfers"
        existing.needs_review, existing.review_reason = False, None
        changed = True
    elif (existing.category in _UNCLASSIFIED and c.parsed_category not in _UNCLASSIFIED
          and "category" not in corrected and existing.transaction_type != TransactionType.TRANSFER):
        existing.category = c.parsed_category
        if "merchant" not in corrected:
            existing.needs_review, existing.review_reason = compute_review_status(existing.merchant, existing.category)
        changed = True
    if changed:
        session.add(existing)
    return changed


def _raw_extra_json(ptx) -> str | None:
    extra = dict(ptx.extra_fields or {})
    if ptx.counterparty_iban:
        extra["_counterparty_iban"] = ptx.counterparty_iban
    return json.dumps(extra, ensure_ascii=False) if extra else None


def commit_parsed_import(
    session: Session,
    parsed: ParsedImport,
    account_id: int,
    stored_path: str,
    document_type: DocumentType | None = None,
    row_decisions: dict[int, str] | None = None,
    classified: list | None = None,
) -> CommitResult:
    """Persist a previously-parsed import: creates the ImportRecord, raw
    transactions, and normalized transactions, classifying duplicates
    against the *entire* existing dataset for the account (not just this
    file) with exactly the logic the preview showed.

    row_decisions maps a row's source_row_index to an explicit "skip" or
    "keep" choice, overriding the default: an exact duplicate defaults to
    "skip"; everything else (including a "possible duplicate") defaults to
    "keep" — possible duplicates are never silently discarded.

    Afterwards transfer detection and credit-card reconciliation run for
    the affected date range.
    """
    account = session.get(Account, account_id)
    if account is None:
        raise ImportServiceError(tr("Unknown account_id={account_id}", account_id=account_id))

    if parsed.ambiguous or parsed.has_errors:
        details = "; ".join(i.message for i in parsed.issues if i.severity == "error" or parsed.ambiguous)
        raise ImportServiceError(
            tr("This file could not be reliably parsed and was not imported.") + (f" {details}" if details else "")
        )

    mismatch = document_account_mismatch(parsed, account) or statement_already_imported(session, parsed, account)
    if mismatch:
        raise ImportServiceError(mismatch)

    resolved_document_type = document_type or parsed.document_type
    decision_map = row_decisions or {}

    existing = find_existing_import_by_checksum(session, parsed.file_checksum)
    if existing is not None:
        raise ImportServiceError(tr(
            "This file appears to have already been imported ({count} transactions, on {date}).",
            count=existing.detected_transaction_count, date=format_date(existing.imported_at),
        ))

    # (`classified`: the caller just did it for these rows, under the same lock — not twice)
    if classified is None:
        classified = classify_import_rows(session, account, parsed.transactions, parsed.filename,
                                          (parsed.period_start, parsed.period_end))
    classifications = {c.source_row_index: c for c in classified}

    import_record = ImportRecord(
        filename=parsed.filename,
        stored_path=stored_path,
        file_checksum=parsed.file_checksum,
        document_type=resolved_document_type,
        account_id=account_id,
        period_start=date.fromisoformat(parsed.period_start) if parsed.period_start else None,
        period_end=date.fromisoformat(parsed.period_end) if parsed.period_end else None,
        status=ImportStatus.IMPORTED,
        detected_transaction_count=len(parsed.transactions),
    )
    session.add(import_record)
    session.flush()  # obtain import_record.id

    transactions_created = 0
    duplicates_flagged = 0
    rows_skipped = 0
    enriched = 0
    to_locate: list[int] = []
    new_transactions: list[Transaction] = []
    row_tx: dict[int, Transaction | int] = {}  # a row's booking: new, or the one it duplicated

    # The raw rows first, written together: a booking needs its raw row's id,
    # and one flush per row made a year's export thousands of round trips.
    raw_rows = [
        RawTransaction(
            import_id=import_record.id,
            source_row_index=ptx.source_row_index,
            original_date_text=ptx.original_date_text,
            original_description=ptx.original_description,
            original_amount_text=ptx.original_amount_text,
            original_currency_text=ptx.original_currency_text,
            extra_fields_json=_raw_extra_json(ptx),
        )
        for ptx in parsed.transactions
    ]
    session.add_all(raw_rows)
    session.flush()

    for ptx, raw in zip(parsed.transactions, raw_rows, strict=True):
        if ptx.parsed_date is None or ptx.parsed_amount_minor is None:
            # Cannot normalize a transaction we couldn't parse the date/amount
            # for; it is still preserved as a raw record for auditability,
            # but no Transaction row is created for it.
            continue

        c = classifications[ptx.source_row_index]
        default_decision = "skip" if c.status == "exact_duplicate" else "keep"
        if decision_map.get(ptx.source_row_index, default_decision) == "skip":
            rows_skipped += 1
            duplicates_flagged += 1
            if c.match is not None:
                # remember which booking this row is, so e.g. a card statement
                # still finds its purchases when they came from another file first
                raw.duplicate_of_transaction_id = c.match.id
                session.add(raw)
            if c.status == "exact_duplicate" and c.match is not None:
                enriched += int(_enrich_existing(session, c.match.id, ptx, c))
            if c.match is not None:
                to_locate.append(c.match.id)  # this row may tell its place (see location_service)
                row_tx[ptx.source_row_index] = c.match.id
            continue

        # "keep" — always a genuine transaction, even if it was an exact
        # fingerprint match: the user has said it's a separate transaction.
        needs_review, review_reason = c.needs_review, c.review_reason
        if c.status != "new" and c.transaction_type != TransactionType.TRANSFER:
            needs_review, review_reason = compute_review_status(c.parsed_merchant, c.parsed_category)
            if decision_map.get(ptx.source_row_index) == "keep":
                # the user said: a booking of its own, although it looked like one already there —
                # never merged with it later (twin_merge)
                raw.kept_by_user = True
                session.add(raw)

        tx = Transaction(
            raw_transaction_id=raw.id,
            account_id=account_id,
            transaction_date=date.fromisoformat(ptx.parsed_date),
            value_date=date.fromisoformat(ptx.extra_fields["_value_date"]) if ptx.extra_fields.get("_value_date") else None,
            normalized_description=(ptx.original_description or "").strip(),
            merchant=c.parsed_merchant,
            category=c.parsed_category,
            amount_minor=ptx.parsed_amount_minor,
            currency=ptx.parsed_currency or account.currency,
            transaction_type=c.transaction_type,
            duplicate_fingerprint=c.fingerprint,
            is_duplicate=False,
            duplicate_of_id=None,
            is_transfer=c.transaction_type == TransactionType.TRANSFER,
            needs_review=needs_review,
            review_reason=review_reason,
        )
        session.add(tx)
        new_transactions.append(tx)
        row_tx[ptx.source_row_index] = tx
        transactions_created += 1

    if parsed.points:
        session.flush()  # the new bookings' ids
        store_points(session, import_record, parsed,
                     {row: t if isinstance(t, int) else t.id for row, t in row_tx.items()})

    credit_card_statement = None
    if resolved_document_type == DocumentType.CREDIT_CARD_STATEMENT:
        credit_card_statement = CreditCardStatement(
            account_id=account_id,
            import_id=import_record.id,
            statement_period_start=import_record.period_start,
            statement_period_end=import_record.period_end,
            statement_total_minor=parsed.statement_total_minor,
            other_totals_json=json.dumps(parsed.other_totals) if parsed.other_totals else None,
            currency=account.currency,
        )
        session.add(credit_card_statement)

    session.commit()
    session.refresh(import_record)
    if credit_card_statement is not None:
        session.refresh(credit_card_statement)

    try:
        run_post_import_matching(session, import_record, credit_card_statement)
        refresh_locations(session, [t.id for t in new_transactions] + to_locate)
    except Exception:  # noqa: BLE001 — the import itself is stored; these are redone on start-up
        session.rollback()
        logger.exception("Matching after an import failed")
    session.refresh(import_record)

    return CommitResult(
        import_record=import_record,
        transactions_created=transactions_created,
        duplicates_flagged=duplicates_flagged,
        rows_skipped=rows_skipped,
        credit_card_statement=credit_card_statement,
        transactions_enriched=enriched,
    )


def run_post_import_matching(
    session: Session, import_record: ImportRecord, statement: CreditCardStatement | None
) -> None:
    """Credit-card reconciliation first (so a card payment is claimed as
    the statement's settlement before generic transfer detection could
    pair it with something else), then transfer detection — both limited
    to the dates this import touched."""
    from app.normalization.transfers import IBAN_MATCH_MAX_DAY_GAP
    from app.reconciliation.engine import (
        derive_statements_from_exports,
        link_pending_payments,
        reconcile_statement,
        retire_derived_statements,
    )
    from app.services.transfer_detection_service import detect_and_mark_transfers

    if statement is not None:
        retire_derived_statements(session, statement)
        reconcile_statement(session, statement.id, auto_match=True)
    derive_statements_from_exports(session)
    link_pending_payments(session)  # this file may have brought, or another statement claimed, a debit

    window = None
    if import_record.period_start and import_record.period_end:
        gap = timedelta(days=IBAN_MATCH_MAX_DAY_GAP)  # the widest pairing window
        window = (import_record.period_start - gap, import_record.period_end + gap)
    detect_and_mark_transfers(session, date_window=window)
    from app.services.transfer_marking import sort_card_bill_payees

    sort_card_bill_payees(session)
