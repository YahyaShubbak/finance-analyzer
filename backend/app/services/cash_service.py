"""Cash: a wallet account the user books into by hand.

Money taken from a cash machine is not spent yet, it moves into the wallet:
with an active cash account, bookings of the category "Cash" on the other
accounts become transfers (no expense, no income) and add to the wallet.
What is paid in cash, and cash that never came from an account (a debt paid
back, a present), is entered by hand in the cash account with a category.
Counting the wallet books the difference to what the app expects as cash
spent on something unknown.

Entries hang on one import record per cash account ("manual"), as every
booking needs its raw row: categories, lists, budgets and backups then work
for them as for imported ones.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, func, select

from app.db.models import (
    Account,
    AccountType,
    DocumentType,
    ImportRecord,
    ImportStatus,
    RawTransaction,
    Transaction,
    TransactionType,
)
from app.services.duplicate_detection import compute_duplicate_fingerprint
from app.services.transfer_marking import manually_corrected_type_ids, natural_type

CASH_CATEGORY = "Cash"
MANUAL_SOURCE = "manual"


class CashError(ValueError):
    """Not a cash account (or not its entry); the API words it."""
    pass


def active_wallet(session: Session) -> Account | None:
    return session.exec(
        select(Account).where(Account.account_type == AccountType.CASH, Account.is_archived == False)  # noqa: E712
        .order_by(Account.id)
    ).first()


def _withdrawals(session: Session):
    """Cash taken out on the other accounts: category Cash, money out."""
    return select(Transaction).join(Account, Account.id == Transaction.account_id).where(
        Account.account_type != AccountType.CASH,
        Transaction.category == CASH_CATEGORY,
        Transaction.amount_minor < 0,
        Transaction.is_duplicate == False,  # noqa: E712
        Transaction.transfer_pair_id == None,  # noqa: E711
        Transaction.settles_statement_id == None,  # noqa: E711
    )


def sync_withdrawals(session: Session) -> int:
    """Withdrawals are transfers into the wallet while there is one, and
    expenses again without one. A type the user set by hand stays. Returns
    how many bookings changed."""
    wallet = active_wallet(session) is not None
    corrected = manually_corrected_type_ids(session)
    changed = 0
    for tx in session.exec(_withdrawals(session)).all():
        if tx.id in corrected or tx.is_transfer == wallet:
            continue
        tx.is_transfer = wallet
        tx.transaction_type = TransactionType.TRANSFER if wallet else natural_type(tx.amount_minor)
        session.add(tx)
        changed += 1
    if changed:
        session.commit()
    return changed


def withdrawn_minor(session: Session) -> int:
    """Cash taken into the wallet (positive)."""
    total = session.exec(
        select(func.coalesce(func.sum(Transaction.amount_minor), 0))
        .where(Transaction.id.in_(_withdrawals(session).where(Transaction.is_transfer == True)  # noqa: E712
                                  .with_only_columns(Transaction.id)))
    ).one()
    return -int(total)


def _manual_import(session: Session, account: Account) -> ImportRecord:
    record = session.exec(select(ImportRecord).where(
        ImportRecord.account_id == account.id, ImportRecord.source_key == MANUAL_SOURCE)).first()
    if record is None:
        record = ImportRecord(
            filename="manual", stored_path="", file_checksum=f"manual-{account.id}",
            document_type=DocumentType.UNKNOWN, account_id=account.id,
            status=ImportStatus.IMPORTED, source_key=MANUAL_SOURCE,
        )
        session.add(record)
        session.flush()
    return record


def wallet_account(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None or account.account_type != AccountType.CASH:
        raise CashError
    return account


def add_entry(session: Session, account_id: int, on: date, amount_minor: int, category: str,
              note: str | None = None) -> Transaction:
    """A cash booking: negative paid out, positive taken in."""
    if amount_minor == 0:
        raise CashError
    account = wallet_account(session, account_id)
    record = _manual_import(session, account)
    row = (session.exec(select(func.max(RawTransaction.source_row_index))
                        .where(RawTransaction.import_id == record.id)).one() or 0) + 1
    description = (note or "").strip() or category
    raw = RawTransaction(
        import_id=record.id, source_row_index=row, original_date_text=on.isoformat(),
        original_description=description, original_amount_text=str(amount_minor),
        original_currency_text=account.currency,
    )
    session.add(raw)
    session.flush()
    tx = Transaction(
        raw_transaction_id=raw.id, account_id=account.id, transaction_date=on,
        normalized_description=description, merchant=None, category=category,
        amount_minor=amount_minor, currency=account.currency,
        transaction_type=natural_type(amount_minor),
        duplicate_fingerprint=compute_duplicate_fingerprint(account.id, on.isoformat(), amount_minor, f"{description}#{row}"),
        notes=(note or "").strip() or None,
    )
    session.add(tx)
    record.detected_transaction_count += 1
    session.add(record)
    session.commit()
    session.refresh(tx)
    return tx


def delete_entry(session: Session, account_id: int, transaction_id: int) -> None:
    tx = session.get(Transaction, transaction_id)
    if tx is None or tx.account_id != wallet_account(session, account_id).id:
        raise CashError
    raw = session.get(RawTransaction, tx.raw_transaction_id)
    session.delete(tx)
    session.flush()
    if raw is not None:
        session.delete(raw)
    session.commit()


@dataclass(frozen=True)
class WalletBalance:
    withdrawn_minor: int  # taken from the accounts
    entries_minor: int    # booked by hand (in minus out)
    balance_minor: int    # what should be in the wallet


def wallet_balance(session: Session, account_id: int) -> WalletBalance:
    account = wallet_account(session, account_id)
    entries = int(session.exec(select(func.coalesce(func.sum(Transaction.amount_minor), 0))
                               .where(Transaction.account_id == account.id)).one())
    withdrawn = withdrawn_minor(session) if account.id == getattr(active_wallet(session), "id", None) else 0
    return WalletBalance(withdrawn, entries, (account.opening_balance_minor or 0) + withdrawn + entries)


def count_wallet(session: Session, account_id: int, on: date, counted_minor: int, label: str) -> Transaction | None:
    """The user counted the cash: the gap to the expected balance is cash
    spent on something not booked (or found). None when it matches."""
    gap = counted_minor - wallet_balance(session, account_id).balance_minor
    if gap == 0:
        return None
    return add_entry(session, account_id, on, gap, CASH_CATEGORY, label)
