"""Categories the user creates ("Darlehen", "Schulden") next to the built-in
ones. Transactions, learned rules and budgets refer to a category by name,
so renaming and deleting carry those along."""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from app.db.models import Budget, CategoryRule, CustomCategory, Transaction
from app.i18n import tr
from app.normalization.category import BUILT_IN_CATEGORIES
from app.normalization.review import CATEGORY_UNCLEAR

MAX_NAME_LENGTH = 40


class CategoryError(Exception):
    """Invalid input (422)."""


class CategoryConflict(CategoryError):
    """The name is taken (409)."""


class CategoryNotFound(CategoryError):
    """No such custom category (404)."""


@dataclass
class CategoryInfo:
    name: str
    built_in: bool
    id: int | None
    transaction_count: int


def _usage(session: Session) -> dict[str, int]:
    rows = session.exec(
        select(Transaction.category, func.count(Transaction.id))
        .where(Transaction.is_duplicate == False)  # noqa: E712
        .group_by(Transaction.category)
    ).all()
    return {category: count for category, count in rows if category}


def _adopt_used_names(session: Session, usage: dict[str, int]) -> None:
    """A category that is in use but was never created — typed in with an
    older version (before categories could be created), or sent to the API
    directly — becomes one of the user's categories. It can then be chosen,
    renamed and deleted like the others, instead of living on in bookings,
    rules and budgets where nothing reaches it. (Of two spellings that
    differ only in case, the one used most.)"""
    known = {name.casefold() for name in BUILT_IN_CATEGORIES}
    known |= {name.casefold() for name in session.exec(select(CustomCategory.name)).all()}
    used = sorted(usage, key=lambda name: (-usage[name], name))
    used += sorted(set(session.exec(select(CategoryRule.category)).all()) | set(session.exec(select(Budget.category)).all()))
    adopted = False
    for name in used:
        if name and name.strip() and name.casefold() not in known:
            known.add(name.casefold())
            session.add(CustomCategory(name=name))
            adopted = True
    if not adopted:
        return
    try:
        session.commit()
    except IntegrityError:  # another request adopted them at the same moment
        session.rollback()


def list_categories(session: Session) -> list[CategoryInfo]:
    usage = _usage(session)
    _adopt_used_names(session, usage)
    custom = session.exec(select(CustomCategory).order_by(CustomCategory.name)).all()
    return [CategoryInfo(name, True, None, usage.get(name, 0)) for name in BUILT_IN_CATEGORIES] + [
        CategoryInfo(c.name, False, c.id, usage.get(c.name, 0)) for c in custom
    ]


def _valid_name(session: Session, name: str, own_id: int | None = None) -> str:
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not name:
        raise CategoryError(tr("Please enter a name."))
    if len(name) > MAX_NAME_LENGTH:
        raise CategoryError(tr("A category name can have at most {count} characters.", count=MAX_NAME_LENGTH))
    if name.casefold() in {b.casefold() for b in BUILT_IN_CATEGORIES}:
        raise CategoryConflict(tr("“{name}” is a built-in category.", name=name))
    for other in session.exec(select(CustomCategory)).all():
        if other.id != own_id and other.name.casefold() == name.casefold():
            raise CategoryConflict(tr("The category “{name}” already exists.", name=other.name))
    return name


def _get(session: Session, category_id: int) -> CustomCategory:
    category = session.get(CustomCategory, category_id)
    if category is None:
        raise CategoryNotFound(tr("Category not found."))
    return category


def create_category(session: Session, name: str) -> CustomCategory:
    category = CustomCategory(name=_valid_name(session, name))
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


def rename_category(session: Session, category_id: int, name: str) -> CustomCategory:
    category = _get(session, category_id)
    new_name = _valid_name(session, name, own_id=category.id)
    old_name = category.name
    if new_name != old_name:
        if session.exec(select(Budget).where(Budget.category == new_name)).first() is not None:
            raise CategoryConflict(tr("There is already a budget for “{name}”. Remove it first.", name=new_name))
        _retarget(session, old_name, new_name)
        category.name = new_name
        session.add(category)
    session.commit()
    session.refresh(category)
    return category


def _retarget(session: Session, old: str, new: str) -> None:
    for tx in session.exec(select(Transaction).where(Transaction.category == old)).all():
        tx.category = new
        session.add(tx)
    for rule in session.exec(select(CategoryRule).where(CategoryRule.category == old)).all():
        rule.category = new
        session.add(rule)
    for budget in session.exec(select(Budget).where(Budget.category == old)).all():
        budget.category = new
        session.add(budget)


def delete_category(session: Session, category_id: int, replacement: str | None) -> int:
    """Deletes a custom category. Its transactions get `replacement` — or,
    without one, "Other Expense"/"Other Income" and a place in the review
    queue. Rules learned for it and its budget go with it. Returns how many
    transactions were moved."""
    category = _get(session, category_id)
    if replacement is not None:
        replacement = replacement.strip()
        known = set(BUILT_IN_CATEGORIES) | {c.name for c in session.exec(select(CustomCategory)).all()}
        if replacement not in known or replacement == category.name:
            raise CategoryError(tr("Unknown replacement category “{name}”.", name=replacement))
    moved = 0
    for tx in session.exec(select(Transaction).where(Transaction.category == category.name)).all():
        if replacement is not None:
            tx.category = replacement
        else:
            tx.category = "Other Income" if tx.amount_minor > 0 else "Other Expense"
            tx.needs_review, tx.review_reason = True, CATEGORY_UNCLEAR
        session.add(tx)
        moved += 1
    for rule in session.exec(select(CategoryRule).where(CategoryRule.category == category.name)).all():
        session.delete(rule)
    for budget in session.exec(select(Budget).where(Budget.category == category.name)).all():
        session.delete(budget)
    session.delete(category)
    session.commit()
    return moved
