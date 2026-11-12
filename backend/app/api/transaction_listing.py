"""What every list of bookings in the API shares: the booking as it is
shown, the search over description and merchant, and the order."""
from __future__ import annotations

from typing import Literal

from sqlmodel import func

from app.db.models import Account, Transaction
from app.db.session import fold_plain, fold_text
from app.normalization.review import review_reason_text
from app.schemas.transaction import TransactionRead


def transaction_read(t: Transaction, account_name: str) -> TransactionRead:
    source_filename = None
    if t.raw_transaction and t.raw_transaction.import_record:
        source_filename = t.raw_transaction.import_record.filename
    return TransactionRead(
        id=t.id,
        account_id=t.account_id,
        account_name=account_name,
        transaction_date=t.transaction_date,
        normalized_description=t.normalized_description,
        merchant=t.merchant,
        category=t.category,
        amount_minor=t.amount_minor,
        currency=t.currency,
        transaction_type=t.transaction_type,
        is_duplicate=t.is_duplicate,
        is_transfer=t.is_transfer,
        needs_review=t.needs_review,
        review_reason=review_reason_text(t.review_reason),
        notes=t.notes,
        source_filename=source_filename,
        country=t.country,
        city=t.city,
        online=t.online,
    )


TransactionSort = Literal["date", "amount", "account", "type"]
SortOrder = Literal["asc", "desc"]


def search_filter(search: str):
    """Description or merchant contains `search`. Umlauts and case don't
    matter ("BÄCKEREI" finds "Baeckerei", "Muller" finds "Müller"); LIKE
    wildcards are escaped so "50%" or "_" are searched literally."""
    def pattern(text: str) -> str:
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    like, plain = pattern(fold_text(search)), pattern(fold_plain(search))
    return (
        func.fold(Transaction.normalized_description).like(like, escape="\\")
        | func.fold(Transaction.merchant).like(like, escape="\\")
        | func.fold_plain(Transaction.normalized_description).like(plain, escape="\\")
        | func.fold_plain(Transaction.merchant).like(plain, escape="\\")
    )


def sorted_by(stmt, sort: TransactionSort, order: SortOrder):
    """The chosen column (an amount: signed, so the biggest expense is the
    smallest), then newest first — a stable order across pages."""
    column = {
        "date": Transaction.transaction_date,
        "amount": Transaction.amount_minor,
        "account": func.lower(Account.name),
        "type": Transaction.transaction_type,
    }[sort]
    if sort == "account":
        stmt = stmt.join(Account, Account.id == Transaction.account_id)
    return stmt.order_by(column.asc() if order == "asc" else column.desc(),
                         Transaction.transaction_date.desc(), Transaction.id.desc())
