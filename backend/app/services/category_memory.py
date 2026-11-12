"""What the app already knows about a merchant: the category most of its
other transactions have — set by a rule, by the card network's merchant
category (e.g. in a card export), or by the user.

Used when no rule names a transaction's category: the same merchant on
another account, or a refund from a shop whose purchases are sorted, gets
that category instead of "Other Expense".
"""
from __future__ import annotations

from collections import Counter, defaultdict

from sqlmodel import Session, select

from app.db.models import Transaction, TransactionType, UserCorrection
from app.normalization.category import NO_SIGNAL_CATEGORIES

# Not knowledge about a merchant: unsorted, or money between own accounts.
_NO_KNOWLEDGE = {None, *NO_SIGNAL_CATEGORIES}
# A merchant's category counts when it is clearly the usual one.
_MIN_SHARE = 2 / 3


def merchant_key(merchant: str | None) -> str | None:
    key = " ".join((merchant or "").lower().split())
    return key or None


def category_memory(session: Session) -> CategoryMemory:
    """The memory for the current data: built by reading every booking, so
    remembered until the data changes."""
    from app.db.session import remembered

    return remembered(session, "category_memory", lambda: CategoryMemory(session))


class CategoryMemory:
    def __init__(self, session: Session):
        corrected = set(session.exec(
            select(UserCorrection.transaction_id).where(UserCorrection.field == "category")
        ).all())
        votes: dict[tuple[str, bool], Counter] = defaultdict(Counter)
        for tx_id, merchant, category, tx_type, is_transfer in session.exec(
            select(Transaction.id, Transaction.merchant, Transaction.category, Transaction.transaction_type,
                   Transaction.is_transfer).where(Transaction.is_duplicate == False)  # noqa: E712
        ).all():
            key = merchant_key(merchant)
            if key is None or category in _NO_KNOWLEDGE or is_transfer:
                continue
            # the user's own choice weighs more than a rule's
            votes[(key, tx_type == TransactionType.INCOME)][category] += 3 if tx_id in corrected else 1
        self._known: dict[tuple[str, bool], str] = {}
        for key, counter in votes.items():
            category, n = counter.most_common(1)[0]
            if n >= _MIN_SHARE * sum(counter.values()):
                self._known[key] = category

    def category_for(self, merchant: str | None, is_income: bool) -> str | None:
        key = merchant_key(merchant)
        return self._known.get((key, is_income)) if key else None
