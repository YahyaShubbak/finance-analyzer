"""Reading a file into a preview — before anything is stored, and without
the database: which reader a file gets, and what the result says about the
account it is meant for.

(On its own, below app.services.import_service: the start-up jobs that
read stored files again need the readers, not the whole import.)
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from app.db.models import Account, AccountType, DocumentType
from app.i18n import tr
from app.importers.base import ParsedImport, ParseOptions
from app.importers.csv_importer import CSVImporter
from app.importers.pdf_importer import PDFImporter
from app.importers.xlsx_importer import XLSXImporter

logger = logging.getLogger("finance")


class ImportServiceError(Exception):
    pass


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
