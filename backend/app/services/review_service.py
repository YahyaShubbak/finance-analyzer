"""The review queue grouped by payee, and one category for a whole group.

A group is what one learned category covers together: the same payee, or
the same chain (app.services.chains.payee_name) — biggest groups first, so
many bookings are sorted with one choice, side by side to see they fit.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.db.chunks import chunked
from app.db.models import CategoryRule, RawTransaction, Transaction, UserCorrection, utcnow
from app.services.category_suggestion import UnsortedSuggestions
from app.services.chains import chain_index, payee_name
from app.services.rule_service import category_rule_source, learn_category

# key of a booking whose text names no payee: a group of its own
_SINGLE = "tx:"


@dataclass
class ReviewGroup:
    key: str
    label: str
    transactions: list[Transaction]
    suggested_category: str | None = None

    @property
    def learnable(self) -> bool:
        """A rule can be learned for it (not for a booking without a usable payee)."""
        return not self.key.startswith(_SINGLE)

    @property
    def total_minor(self) -> int:
        return sum(t.amount_minor for t in self.transactions)


@dataclass
class ReviewGroupsPage:
    groups: list[ReviewGroup]
    total_groups: int
    total_transactions: int


def review_groups(session: Session, page: int, page_size: int) -> ReviewGroupsPage:
    txs = session.exec(
        select(Transaction).where(Transaction.needs_review == True)  # noqa: E712
        .options(selectinload(Transaction.raw_transaction).selectinload(RawTransaction.import_record))
        .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
    ).all()
    chains = chain_index(session)
    grouped: dict[str, ReviewGroup] = {}
    for t in txs:
        field, _source = category_rule_source(t)
        name = payee_name(t, chains)
        key = f"{field}:{name.lower()}" if name else f"{_SINGLE}{t.id}"
        if key not in grouped:
            grouped[key] = ReviewGroup(key=key, label=name or t.merchant or t.normalized_description, transactions=[])
        grouped[key].transactions.append(t)

    order = sorted(grouped.values(), key=lambda g: (not g.learnable, -len(g.transactions), -abs(g.total_minor)))
    chosen = order[(page - 1) * page_size: page * page_size]
    suggestions = UnsortedSuggestions(session)
    for group in chosen:
        group.suggested_category = suggestions.for_transaction(group.transactions[0])
    return ReviewGroupsPage(groups=chosen, total_groups=len(order), total_transactions=len(txs))


class UnknownTransactionError(LookupError):
    pass


@dataclass
class Assignment:
    updated: int
    rule: CategoryRule | None = None
    applied_to: int = 0  # other existing bookings the learned rule changed


def assign_category(session: Session, transaction_ids: list[int], category: str, learn: bool = False,
                    leave_out: set[int] | frozenset[int] = frozenset()) -> Assignment:
    """One category for several bookings (a review group), as the user's
    own choice. With `learn`, a rule is learned from the first one's payee
    as well — it leaves out the bookings the user left out of the group."""
    ids = list(dict.fromkeys(transaction_ids))
    found = {t.id: t for chunk in chunked(ids)
             for t in session.exec(select(Transaction).where(Transaction.id.in_(chunk))).all()}
    if len(found) != len(ids):
        raise UnknownTransactionError
    for tx_id in ids:
        tx = found[tx_id]
        if tx.category != category:
            session.add(UserCorrection(transaction_id=tx.id, field="category", old_value=tx.category, new_value=category))
            tx.category = category
        tx.needs_review, tx.review_reason = False, None
        tx.updated_at = utcnow()
        session.add(tx)
    # left out of the group by the user: not this category — and no rule or the
    # merchant's usual category may sort it so later; it stays to be checked
    for chunk in chunked([i for i in leave_out if i not in found]):
        for tx in session.exec(select(Transaction).where(Transaction.id.in_(chunk))).all():
            session.add(UserCorrection(transaction_id=tx.id, field="category", old_value=tx.category,
                                       new_value=tx.category or ""))
    session.flush()
    result = Assignment(updated=len(ids))
    if learn:
        # after the group's own corrections: the count is of other bookings the rule changed
        lesson = learn_category(session, ids[0], category, leave_out=set(leave_out))
        result.rule, result.applied_to = lesson.rule, lesson.applied_to
    session.commit()
    return result
