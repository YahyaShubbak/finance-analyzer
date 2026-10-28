"""Budget CRUD (upsert-by-category) and budget-vs-actual status
computation. Actual spend reuses analytics_service.compute_category_breakdown
so budgets automatically inherit the exact same is_duplicate/is_transfer/
archived-account exclusion rules as every other aggregate in the app —
there is deliberately no separate query here that could silently drift
from what Dashboard/Reports consider "real" spending.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlmodel import Session, select

from app.db.models import Budget, utcnow
from app.i18n import tr
from app.services import analytics_service

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class BudgetServiceError(Exception):
    pass


def list_budgets(session: Session) -> list[Budget]:
    return list(session.exec(select(Budget).order_by(Budget.category)).all())


def upsert_budget(session: Session, category: str, amount_minor: int, currency: str = "EUR") -> Budget:
    """Create-or-update semantics keyed on category — a second upsert for
    the same category updates the existing row in place rather than
    creating a duplicate (the unique index on `category` is a DB-level
    backstop against a race between the lookup and the insert)."""
    budget = session.exec(select(Budget).where(Budget.category == category)).first()
    if budget:
        budget.amount_minor = amount_minor
        budget.currency = currency
        budget.updated_at = utcnow()
    else:
        budget = Budget(category=category, amount_minor=amount_minor, currency=currency)

    session.add(budget)
    session.commit()
    session.refresh(budget)
    return budget


def delete_budget(session: Session, budget_id: int) -> bool:
    budget = session.get(Budget, budget_id)
    if budget is None:
        return False
    session.delete(budget)
    session.commit()
    return True


def _month_bounds(month: str) -> tuple[date, date]:
    if not MONTH_RE.match(month):
        raise BudgetServiceError(tr("Invalid month '{month}' — expected format YYYY-MM.", month=month))
    year, m = (int(x) for x in month.split("-"))
    start = date(year, m, 1)
    next_month_start = date(year + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
    end = next_month_start - timedelta(days=1)
    return start, end


@dataclass
class BudgetStatus:
    category: str
    budget_minor: int
    actual_minor: int
    currency: str

    @property
    def remaining_minor(self) -> int:
        return self.budget_minor - self.actual_minor

    @property
    def percent_used(self) -> float:
        if self.budget_minor == 0:
            return 0.0
        return round(self.actual_minor / self.budget_minor * 100, 1)

    @property
    def over_budget(self) -> bool:
        return self.actual_minor > self.budget_minor


def compute_budget_status(session: Session, month: str) -> list[BudgetStatus]:
    """month = 'YYYY-MM'. Only categories that have a budget row are
    itemized (no zero-filled rows for un-budgeted categories) — this
    endpoint answers "how am I doing against my budgets", not "give me
    every category"."""
    budgets = list_budgets(session)
    if not budgets:
        return []

    start, end = _month_bounds(month)
    breakdown = analytics_service.compute_category_breakdown(session, start=start, end=end)

    # actual spend per (category, currency) — a budget's actual_minor only
    # counts spend in the budget's own currency, so a foreign-currency
    # purchase filed under the same category can't silently inflate a
    # budget denominated in a different currency.
    actual_by_key: dict[tuple[str, str], int] = defaultdict(int)
    for category, currency, amount in breakdown:
        actual_by_key[(category, currency)] += amount

    return [
        BudgetStatus(
            category=b.category, budget_minor=b.amount_minor,
            actual_minor=max(0, actual_by_key.get((b.category, b.currency), 0)),  # more refunds than spending: 0
            currency=b.currency,
        )
        for b in budgets
    ]
