"""Aggregate totals for the dashboard and reports. All aggregation happens
here in the backend (as SQL GROUP BY queries, so it stays fast with
hundreds of thousands of transactions) — the frontend only ever renders
numbers it's given.

Income vs. expense follows the transaction TYPE, not just the sign:

* income  = sum of INCOME transactions (a negative one, e.g. a salary
  correction, reduces income);
* expense = minus the sum of EXPENSE transactions — so a refund (positive,
  typed EXPENSE, the default for money in on a credit card) reduces
  spending instead of counting as income;
* UNKNOWN falls back to the sign; transfers and duplicates are excluded.

A user correcting a transaction's type therefore changes the totals.

Currency handling: every aggregate groups by `Transaction.currency`
rather than blindly summing `amount_minor` across currencies. When exactly
one currency is present (the common case) the shape stays simple; when
more than one is present, the blended total is left unset and a
per-currency breakdown is returned instead, so the UI never displays a
fabricated blended number.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, case
from sqlmodel import Session, func, select

from app.db.models import Account, CreditCardStatement, Transaction, TransactionType

_income_part = case(
    (Transaction.transaction_type == TransactionType.INCOME, Transaction.amount_minor),
    (and_(Transaction.transaction_type == TransactionType.UNKNOWN, Transaction.amount_minor > 0),
     Transaction.amount_minor),
    else_=0,
)
_expense_part = case(
    (Transaction.transaction_type == TransactionType.EXPENSE, -Transaction.amount_minor),
    (and_(Transaction.transaction_type == TransactionType.UNKNOWN, Transaction.amount_minor < 0),
     -Transaction.amount_minor),
    else_=0,
)
_is_expense_kind = (Transaction.transaction_type == TransactionType.EXPENSE) | and_(
    Transaction.transaction_type == TransactionType.UNKNOWN, Transaction.amount_minor < 0
)


@dataclass
class CurrencyTotals:
    currency: str
    income_minor: int
    expenses_minor: int
    transaction_count: int

    @property
    def net_minor(self) -> int:
        return self.income_minor - self.expenses_minor


@dataclass
class Totals:
    income_minor: int | None       # None when is_mixed_currency
    expenses_minor: int | None     # None when is_mixed_currency
    transaction_count: int          # always valid — count isn't currency-dependent
    currency: str | None            # the single common currency, or None when mixed/empty
    is_mixed_currency: bool
    by_currency: list[CurrencyTotals] | None = None   # populated only when mixed

    @property
    def net_minor(self) -> int | None:
        if self.income_minor is None:
            return None
        return self.income_minor - self.expenses_minor


def _active_account_ids(session: Session) -> list[int]:
    return list(session.exec(select(Account.id).where(Account.is_archived == False)).all())  # noqa: E712


def _scope_filters(session: Session, account_ids, start, end, transfers: bool = False) -> list:
    # Archived accounts are excluded from aggregate totals by default. An
    # explicit account_ids filter is respected as-is (a caller who names a
    # specific account has made a deliberate choice).
    effective_account_ids = account_ids if account_ids is not None else _active_account_ids(session)
    filters = [
        Transaction.is_duplicate == False,  # noqa: E712
        Transaction.is_transfer == transfers,
        Transaction.account_id.in_(effective_account_ids),
    ]
    if start is not None:
        filters.append(Transaction.transaction_date >= start)
    if end is not None:
        filters.append(Transaction.transaction_date <= end)
    return filters


def _base_query(session: Session, account_ids, start, end):
    """The transactions every aggregate counts (non-duplicate, non-transfer,
    active accounts, in range) — also used by recurring detection."""
    return select(Transaction).where(*_scope_filters(session, account_ids, start, end))


def compute_totals(
    session: Session,
    account_ids: list[int] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> Totals:
    """Sum income/expenses across accounts. Duplicates and transfers
    (including reconciled credit-card payments) are always excluded, so a
    credit-card purchase and its later bill payment are never both counted
    as expenses."""
    rows = session.exec(
        select(
            Transaction.currency,
            func.coalesce(func.sum(_income_part), 0),
            func.coalesce(func.sum(_expense_part), 0),
            func.count(Transaction.id),
        )
        .where(*_scope_filters(session, account_ids, start, end))
        .group_by(Transaction.currency)
        .order_by(Transaction.currency)
    ).all()
    by_currency = [CurrencyTotals(currency=c, income_minor=int(i), expenses_minor=int(e), transaction_count=n)
                   for c, i, e, n in rows]
    count = sum(c.transaction_count for c in by_currency)

    if len(by_currency) <= 1:
        single = by_currency[0] if by_currency else None
        return Totals(
            income_minor=single.income_minor if single else 0,
            expenses_minor=single.expenses_minor if single else 0,
            transaction_count=count,
            currency=single.currency if single else None,
            is_mixed_currency=False,
            by_currency=None,
        )
    return Totals(
        income_minor=None, expenses_minor=None, transaction_count=count,
        currency=None, is_mixed_currency=True, by_currency=by_currency,
    )


def compute_category_breakdown(
    session: Session,
    account_ids: list[int] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[tuple[str, str, int]]:
    """Net expenses grouped by (category, currency), sorted largest-first.
    Refunds are netted against their category; a category whose refunds
    exceed its spending appears with a negative amount (last), so the rows
    always add up to the total expenses."""
    category = func.coalesce(Transaction.category, "Other Expense")
    rows = session.exec(
        select(category, Transaction.currency, func.sum(_expense_part))
        .where(*_scope_filters(session, account_ids, start, end), _is_expense_kind)
        .group_by(category, Transaction.currency)
    ).all()
    return sorted(
        ((cat, currency, int(amount)) for cat, currency, amount in rows if amount),
        key=lambda row: row[2], reverse=True,
    )


def category_transactions_query(
    session: Session,
    category: str,
    currency: str,
    account_ids: list[int] | None = None,
    start: date | None = None,
    end: date | None = None,
):
    """The transactions behind one bar of compute_category_breakdown — same
    scope, same expense filter — so they add up to exactly that amount."""
    return select(Transaction).where(
        *_scope_filters(session, account_ids, start, end),
        _is_expense_kind,
        func.coalesce(Transaction.category, "Other Expense") == category,
        Transaction.currency == currency,
    )


def expense_minor_of(session: Session, query) -> int:
    """Net spending of the transactions a *_transactions_query selects."""
    sub = query.subquery()
    amount = case(
        (sub.c.transaction_type == TransactionType.EXPENSE, -sub.c.amount_minor),
        (and_(sub.c.transaction_type == TransactionType.UNKNOWN, sub.c.amount_minor < 0), -sub.c.amount_minor),
        else_=0,
    )
    return int(session.exec(select(func.coalesce(func.sum(amount), 0))).one())


@dataclass
class LocationBreakdown:
    country: str | None  # None with online=False: the statement names no place
    city: str | None
    online: bool
    currency: str
    amount_minor: int
    transaction_count: int


def compute_location_breakdown(
    session: Session,
    account_ids: list[int] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[LocationBreakdown]:
    """Net expenses per place (country, town; online; unknown) and currency,
    largest first — the same expenses as compute_category_breakdown."""
    rows = session.exec(
        select(
            Transaction.country, Transaction.city, Transaction.online, Transaction.currency,
            func.sum(_expense_part), func.count(Transaction.id),
        )
        .where(*_scope_filters(session, account_ids, start, end), _is_expense_kind)
        .group_by(Transaction.country, Transaction.city, Transaction.online, Transaction.currency)
    ).all()
    items = [
        LocationBreakdown(country=None if online else country, city=None if online else city, online=bool(online),
                          currency=currency, amount_minor=int(amount), transaction_count=count)
        for country, city, online, currency, amount, count in rows
        if amount
    ]
    return sorted(items, key=lambda i: i.amount_minor, reverse=True)


def location_transactions_query(
    session: Session,
    currency: str,
    *,
    country: str | None = None,
    city: str | None = None,
    no_city: bool = False,
    online: bool = False,
    account_ids: list[int] | None = None,
    start: date | None = None,
    end: date | None = None,
):
    """The transactions behind compute_location_breakdown's rows: online
    purchases; or one country (one town of it, or the ones without town);
    or, without country, those with no known place."""
    filters = [*_scope_filters(session, account_ids, start, end), _is_expense_kind, Transaction.currency == currency]
    if online:
        filters.append(Transaction.online == True)  # noqa: E712
    else:
        filters.append(Transaction.online == False)  # noqa: E712
        if country is None:
            filters.append(Transaction.country.is_(None))
        else:
            filters.append(Transaction.country == country)
            if no_city:
                filters.append(Transaction.city.is_(None))
            elif city is not None:
                filters.append(Transaction.city == city)
    return select(Transaction).where(*filters)


@dataclass
class AccountBreakdown:
    account_id: int
    account_name: str
    account_type: str
    currency: str
    income_minor: int
    expenses_minor: int
    net_minor: int
    transaction_count: int


@dataclass
class CurrencyTransfersSummary:
    currency: str
    total_transferred_minor: int
    transfer_count: int


@dataclass
class TransfersSummary:
    total_transferred_minor: int | None   # None when is_mixed_currency
    transfer_count: int                    # always valid
    currency: str | None
    is_mixed_currency: bool
    by_currency: list[CurrencyTransfersSummary] | None = None


def compute_account_breakdown(
    session: Session,
    account_ids: list[int] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[AccountBreakdown]:
    """Income/expenses/net per account for the period — same exclusion
    rules as compute_totals. `currency` is the account's nominal currency;
    an account holding several currencies blends them in its single row (a
    documented limitation of the per-account view)."""
    accounts_by_id = {a.id: a for a in session.exec(select(Account)).all()}
    rows = session.exec(
        select(
            Transaction.account_id,
            func.coalesce(func.sum(_income_part), 0),
            func.coalesce(func.sum(_expense_part), 0),
            func.count(Transaction.id),
        )
        .where(*_scope_filters(session, account_ids, start, end))
        .group_by(Transaction.account_id)
    ).all()

    results = []
    for account_id, income, expenses, count in rows:
        account = accounts_by_id.get(account_id)
        results.append(AccountBreakdown(
            account_id=account_id,
            account_name=account.name if account else "Unknown",
            account_type=account.account_type.value if account else "other",
            currency=account.currency if account else "EUR",
            income_minor=int(income),
            expenses_minor=int(expenses),
            net_minor=int(income) - int(expenses),
            transaction_count=count,
        ))

    results.sort(key=lambda r: r.expenses_minor, reverse=True)
    return results


def compute_transfers_summary(
    session: Session,
    account_ids: list[int] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> TransfersSummary:
    """Total money moved via transfers (including credit-card bill
    payments) in the period — shown for transparency so it's clear this is
    real money movement that is intentionally excluded from income/expense
    totals. Each movement is counted ONCE: when both halves of a pair are
    in scope, only the outgoing half is counted."""
    transfers = session.exec(
        select(Transaction.id, Transaction.amount_minor, Transaction.currency, Transaction.transfer_pair_id,
               Transaction.account_id, Transaction.transaction_date, Transaction.settles_statement_id)
        .where(*_scope_filters(session, account_ids, start, end, transfers=True))
    ).all()
    in_scope_ids = {row[0] for row in transfers}
    # a card's payment line is the other half of the bank debit settling its statement
    card_of_statement = dict(session.exec(select(CreditCardStatement.id, CreditCardStatement.account_id)).all())
    settled = [(card_of_statement.get(st), -amount, day) for _id, amount, _c, _p, _a, day, st in transfers
               if st is not None and amount < 0]

    def other_half_counted(account_id: int, amount: int, day: date) -> bool:
        return any(card == account_id and paid == amount and abs((paid_day - day).days) <= 15
                   for card, paid, paid_day in settled)

    totals: dict[str, list[int]] = {}
    for _tx_id, amount, currency, pair_id, account_id, day, _statement in transfers:
        if pair_id in in_scope_ids and amount > 0:
            continue  # the matching outgoing half is counted instead
        if amount > 0 and pair_id is None and other_half_counted(account_id, amount, day):
            continue  # the card being paid: counted as the bank's debit
        entry = totals.setdefault(currency, [0, 0])
        entry[0] += abs(amount)
        entry[1] += 1

    currencies = sorted(totals)
    count = sum(v[1] for v in totals.values())
    if len(currencies) <= 1:
        currency = currencies[0] if currencies else None
        return TransfersSummary(
            total_transferred_minor=totals[currency][0] if currency else 0, transfer_count=count,
            currency=currency, is_mixed_currency=False, by_currency=None,
        )

    return TransfersSummary(
        total_transferred_minor=None, transfer_count=count, currency=None, is_mixed_currency=True,
        by_currency=[
            CurrencyTransfersSummary(currency=c, total_transferred_minor=totals[c][0], transfer_count=totals[c][1])
            for c in currencies
        ],
    )


def compute_monthly_series(
    session: Session,
    account_ids: list[int] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[tuple[str, str, int, int]]:
    """Income/expenses per (calendar month, currency), sorted
    chronologically. Returns (month "YYYY-MM", currency, income_minor,
    expenses_minor)."""
    month = func.strftime("%Y-%m", Transaction.transaction_date)
    rows = session.exec(
        select(month, Transaction.currency, func.coalesce(func.sum(_income_part), 0),
               func.coalesce(func.sum(_expense_part), 0))
        .where(*_scope_filters(session, account_ids, start, end))
        .group_by(month, Transaction.currency)
        .order_by(month, Transaction.currency)
    ).all()
    return [(m, currency, int(income), int(expenses)) for m, currency, income, expenses in rows]
