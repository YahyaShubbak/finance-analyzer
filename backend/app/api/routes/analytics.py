from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import selectinload
from sqlmodel import Session, func, select

from app.api.params import parse_account_ids
from app.api.transaction_listing import SortOrder, TransactionSort, search_filter, sorted_by, transaction_read
from app.db.models import Account, RawTransaction, Transaction
from app.db.session import get_session
from app.schemas.analytics import (
    AccountBreakdownItem,
    CategoryBreakdownItem,
    CategoryTransactionsResponse,
    CurrencyTotals,
    CurrencyTransfersSummary,
    LocationBreakdownItem,
    LocationTransactionsResponse,
    MonthlyPoint,
    TotalsResponse,
    TransfersSummaryResponse,
)
from app.services import analytics_service

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/totals", response_model=TotalsResponse)
def totals(
    account_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_session),
):
    t = analytics_service.compute_totals(session, parse_account_ids(account_id), start, end)
    return TotalsResponse(
        income_minor=t.income_minor, expenses_minor=t.expenses_minor,
        net_minor=t.net_minor, transaction_count=t.transaction_count,
        currency=t.currency, is_mixed_currency=t.is_mixed_currency,
        by_currency=[
            CurrencyTotals(
                currency=c.currency, income_minor=c.income_minor, expenses_minor=c.expenses_minor,
                net_minor=c.net_minor, transaction_count=c.transaction_count,
            )
            for c in t.by_currency
        ] if t.by_currency else None,
    )


@router.get("/by-category", response_model=list[CategoryBreakdownItem])
def by_category(
    account_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_session),
):
    breakdown = analytics_service.compute_category_breakdown(session, parse_account_ids(account_id), start, end)
    return [CategoryBreakdownItem(category=c, currency=cur, amount_minor=a) for c, cur, a in breakdown]


@router.get("/by-category/transactions", response_model=CategoryTransactionsResponse)
def category_transactions(
    category: str,
    currency: str,
    account_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
    search: str | None = None,
    sort: TransactionSort = "date",
    order: SortOrder = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    session: Session = Depends(get_session),
):
    """The transactions one category bar of /by-category is made of (newest first unless sorted)."""
    query = analytics_service.category_transactions_query(
        session, category, currency, parse_account_ids(account_id), start, end
    )
    return _transactions_page(session, query, page, page_size, search, sort, order)


def _transactions_page(session: Session, query, page: int, page_size: int, search: str | None,
                       sort: TransactionSort, order: SortOrder) -> CategoryTransactionsResponse:
    if search:
        query = query.where(search_filter(search))  # the total shown is of the bookings found
    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    page_items = session.exec(
        sorted_by(query, sort, order)
        .options(selectinload(Transaction.raw_transaction).selectinload(RawTransaction.import_record))
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    account_names = {a.id: a.name for a in session.exec(select(Account)).all()}
    return CategoryTransactionsResponse(
        items=[transaction_read(t, account_names.get(t.account_id, "Unknown")) for t in page_items],
        total=total,
        page=page,
        page_size=page_size,
        amount_minor=analytics_service.expense_minor_of(session, query),
    )


@router.get("/by-location", response_model=list[LocationBreakdownItem])
def by_location(
    account_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_session),
):
    breakdown = analytics_service.compute_location_breakdown(session, parse_account_ids(account_id), start, end)
    return [LocationBreakdownItem(**vars(item)) for item in breakdown]


@router.get("/by-location/transactions", response_model=LocationTransactionsResponse)
def location_transactions(
    currency: str,
    country: str | None = None,
    city: str | None = None,
    no_city: bool = False,
    online: bool = False,
    account_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
    search: str | None = None,
    sort: TransactionSort = "date",
    order: SortOrder = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    session: Session = Depends(get_session),
):
    """The transactions of one place of /by-location (no country: no known place; newest first unless sorted)."""
    query = analytics_service.location_transactions_query(
        session, currency, country=country, city=city, no_city=no_city, online=online,
        account_ids=parse_account_ids(account_id), start=start, end=end,
    )
    return _transactions_page(session, query, page, page_size, search, sort, order)


@router.get("/over-time", response_model=list[MonthlyPoint])
def over_time(
    account_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_session),
):
    series = analytics_service.compute_monthly_series(session, parse_account_ids(account_id), start, end)
    return [MonthlyPoint(month=m, currency=cur, income_minor=i, expenses_minor=e) for m, cur, i, e in series]


@router.get("/by-account", response_model=list[AccountBreakdownItem])
def by_account(
    account_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_session),
):
    breakdown = analytics_service.compute_account_breakdown(session, parse_account_ids(account_id), start, end)
    return [
        AccountBreakdownItem(
            account_id=a.account_id, account_name=a.account_name, account_type=a.account_type,
            currency=a.currency,
            income_minor=a.income_minor, expenses_minor=a.expenses_minor, net_minor=a.net_minor,
            transaction_count=a.transaction_count,
        )
        for a in breakdown
    ]


@router.get("/transfers-summary", response_model=TransfersSummaryResponse)
def transfers_summary(
    account_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_session),
):
    summary = analytics_service.compute_transfers_summary(session, parse_account_ids(account_id), start, end)
    return TransfersSummaryResponse(
        total_transferred_minor=summary.total_transferred_minor, transfer_count=summary.transfer_count,
        currency=summary.currency, is_mixed_currency=summary.is_mixed_currency,
        by_currency=[
            CurrencyTransfersSummary(
                currency=c.currency, total_transferred_minor=c.total_transferred_minor, transfer_count=c.transfer_count,
            )
            for c in summary.by_currency
        ] if summary.by_currency else None,
    )
