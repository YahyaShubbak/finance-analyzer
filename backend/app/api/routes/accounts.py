from __future__ import annotations

import dataclasses
from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.models import Account, AccountType
from app.db.session import get_session
from app.i18n import tr
from app.schemas.account import (
    AccountCreate,
    AccountRead,
    AccountUpdate,
    CashCount,
    CashEntryCreate,
    StatementReminderRead,
    WalletRead,
)
from app.services import cash_service
from app.services.account_service import account_read, compute_account_summaries
from app.services.category_service import list_categories
from app.services.statement_reminders import statement_reminders

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

# Fields where an explicit `null` in the request body means "clear this",
# as opposed to every other field where `null`/absent both mean "leave
# unchanged" — an opening balance is the one thing on an account a user
# should be able to deliberately remove.
_CLEARABLE_FIELDS = {"opening_balance_minor", "opening_balance_date", "iban"}


@router.get("", response_model=list[AccountRead])
def list_accounts(include_archived: bool = False, session: Session = Depends(get_session)):
    stmt = select(Account)
    if not include_archived:
        stmt = stmt.where(Account.is_archived == False)  # noqa: E712
    accounts = session.exec(stmt).all()
    summaries = compute_account_summaries(session)
    return [account_read(a, summaries) for a in accounts]


def _reject_iban_in_use(session: Session, iban: str | None, account_id: int | None = None) -> None:
    """One IBAN, one account: files and transfers are matched to accounts by it."""
    if not iban:
        return
    other = session.exec(select(Account).where(Account.iban == iban, Account.id != account_id)).first()
    if other is not None:
        raise HTTPException(status_code=409, detail=tr(
            "The account '{name}' already has this IBAN.", name=other.name))


@router.get("/statement-reminders", response_model=list[StatementReminderRead])
def list_statement_reminders(session: Session = Depends(get_session)):
    """Statements that should be out by now but are not imported yet."""
    return [StatementReminderRead(**asdict(r)) for r in statement_reminders(session, date.today())]


@router.post("", response_model=AccountRead)
def create_account(payload: AccountCreate, session: Session = Depends(get_session)):
    _reject_iban_in_use(session, payload.iban)
    account = Account(
        name=payload.name, account_type=payload.account_type, currency=payload.currency, iban=payload.iban
    )
    session.add(account)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail=tr("An account named '{name}' already exists.", name=payload.name)) from None
    session.refresh(account)
    if account.account_type == AccountType.CASH:
        cash_service.sync_withdrawals(session)
    return account_read(account, {})


@router.patch("/{account_id}", response_model=AccountRead)
def update_account(account_id: int, payload: AccountUpdate, session: Session = Depends(get_session)):
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail=tr("Account not found"))
    _reject_iban_in_use(session, payload.iban, account.id)

    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None or field in _CLEARABLE_FIELDS:
            setattr(account, field, value)

    session.add(account)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail=tr("An account named '{name}' already exists.", name=payload.name)) from None
    session.refresh(account)
    if account.account_type == AccountType.CASH:
        cash_service.sync_withdrawals(session)  # archived or back: withdrawals follow

    summaries = compute_account_summaries(session)
    return account_read(account, summaries)


def _cash_error(error: cash_service.CashError) -> HTTPException:
    return HTTPException(status_code=404, detail=tr("This is not a cash account."))


@router.get("/{account_id}/wallet", response_model=WalletRead)
def get_wallet(account_id: int, session: Session = Depends(get_session)):
    try:
        return WalletRead(**dataclasses.asdict(cash_service.wallet_balance(session, account_id)))
    except cash_service.CashError as e:
        raise _cash_error(e) from None


@router.post("/{account_id}/cash-entries", response_model=WalletRead)
def add_cash_entry(account_id: int, payload: CashEntryCreate, session: Session = Depends(get_session)):
    if payload.amount_minor == 0:
        raise HTTPException(status_code=422, detail=tr("Enter an amount."))
    if payload.category not in {c.name for c in list_categories(session)}:
        raise HTTPException(status_code=422, detail=tr("Unknown category."))
    try:
        cash_service.add_entry(session, account_id, payload.transaction_date, payload.amount_minor,
                               payload.category, payload.note)
    except cash_service.CashError as e:
        raise _cash_error(e) from None
    return get_wallet(account_id, session)


@router.post("/{account_id}/cash-count", response_model=WalletRead)
def count_cash(account_id: int, payload: CashCount, session: Session = Depends(get_session)):
    try:
        cash_service.count_wallet(session, account_id, payload.counted_on, payload.counted_minor,
                                  tr("Cash count: difference"))
    except cash_service.CashError as e:
        raise _cash_error(e) from None
    return get_wallet(account_id, session)


@router.delete("/{account_id}/cash-entries/{transaction_id}", response_model=WalletRead)
def delete_cash_entry(account_id: int, transaction_id: int, session: Session = Depends(get_session)):
    try:
        cash_service.delete_entry(session, account_id, transaction_id)
    except cash_service.CashError as e:
        raise _cash_error(e) from None
    return get_wallet(account_id, session)
