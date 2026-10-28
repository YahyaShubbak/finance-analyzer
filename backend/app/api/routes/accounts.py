from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.models import Account
from app.db.session import get_session
from app.i18n import tr
from app.schemas.account import AccountCreate, AccountRead, AccountUpdate
from app.services.account_service import AccountSummary, compute_account_summaries

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

# Fields where an explicit `null` in the request body means "clear this",
# as opposed to every other field where `null`/absent both mean "leave
# unchanged" — an opening balance is the one thing on an account a user
# should be able to deliberately remove.
_CLEARABLE_FIELDS = {"opening_balance_minor", "opening_balance_date", "iban"}


def _to_read(account: Account, summaries: dict[int, AccountSummary]) -> AccountRead:
    summary = summaries.get(account.id, AccountSummary(0, 0, account.opening_balance_minor or 0))
    return AccountRead(
        id=account.id,
        name=account.name,
        account_type=account.account_type,
        currency=account.currency,
        iban=account.iban,
        created_at=account.created_at,
        is_archived=account.is_archived,
        transaction_count=summary.transaction_count,
        transactions_balance_minor=summary.transactions_balance_minor,
        opening_balance_minor=account.opening_balance_minor,
        opening_balance_date=account.opening_balance_date,
        current_balance_minor=summary.current_balance_minor,
    )


@router.get("", response_model=list[AccountRead])
def list_accounts(include_archived: bool = False, session: Session = Depends(get_session)):
    stmt = select(Account)
    if not include_archived:
        stmt = stmt.where(Account.is_archived == False)  # noqa: E712
    accounts = session.exec(stmt).all()
    summaries = compute_account_summaries(session)
    return [_to_read(a, summaries) for a in accounts]


def _reject_iban_in_use(session: Session, iban: str | None, account_id: int | None = None) -> None:
    """One IBAN, one account: files and transfers are matched to accounts by it."""
    if not iban:
        return
    other = session.exec(select(Account).where(Account.iban == iban, Account.id != account_id)).first()
    if other is not None:
        raise HTTPException(status_code=409, detail=tr(
            "The account '{name}' already has this IBAN.", name=other.name))


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
    return _to_read(account, {})


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

    summaries = compute_account_summaries(session)
    return _to_read(account, summaries)
