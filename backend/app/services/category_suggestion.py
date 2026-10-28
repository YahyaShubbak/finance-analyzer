"""A suggested category for a transaction no rule could sort, learned from
the user's own sorted transactions (a naive-Bayes model over the words of
merchant and description and the letter groups of the merchant's name —
"SHOP4RUNNER" shares "runner" with sports shops). Runs locally; nothing
leaves the computer.

Only ever a *suggestion* the user confirms: checked on real data it is right
about four times in five for merchants it has never seen — too often wrong
to sort on its own.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from sqlmodel import Session, select

from app.db.models import RawTransaction, Transaction, TransactionType
from app.normalization.category import NO_SIGNAL_CATEGORIES, UNSORTED_CATEGORIES

MIN_CONFIDENCE = 0.8
_NO_LABEL = {None, *NO_SIGNAL_CATEGORIES}
# words every kind of booking has — they tell nothing about the category
_STOP = frozenset("""
    gmbh mbh und der die das lastschrift kartenzahlung einkauf zahlung eur ref sepa end mandat gutschrift
    ueberweisung überweisung belastung vom bei mit fuer für kundenreferenz glaeubiger gläubiger
""".split())


def _features(merchant: str | None, description: str | None) -> set[str]:
    text = f"{merchant or ''} {description or ''}".lower()
    words = {w for w in re.findall(r"[a-zäöüß]{3,}", text) if w not in _STOP}
    grams = set()
    for word in re.findall(r"[a-zäöüß0-9]+", (merchant or "").lower()):
        for n in (4, 5):
            grams |= {"#" + word[i:i + n] for i in range(len(word) - n + 1)}
    return words | grams


class CategorySuggester:
    def __init__(self, session: Session):
        self._count: dict[bool, Counter] = defaultdict(Counter)        # is_income -> category -> n
        self._features: dict[tuple[bool, str], Counter] = defaultdict(Counter)
        self._vocab: dict[bool, set[str]] = defaultdict(set)
        for merchant, description, category, tx_type in session.exec(
            select(Transaction.merchant, RawTransaction.original_description, Transaction.category, Transaction.transaction_type)
            .join(RawTransaction, RawTransaction.id == Transaction.raw_transaction_id)
            .where(Transaction.is_duplicate == False, Transaction.is_transfer == False)  # noqa: E712
        ).all():
            if category in _NO_LABEL:
                continue
            income = tx_type == TransactionType.INCOME
            f = _features(merchant, description)
            self._count[income][category] += 1
            self._features[(income, category)].update(f)
            self._vocab[income] |= f
        self._totals = {key: sum(c.values()) for key, c in self._features.items()}

    def suggest(self, merchant: str | None, description: str | None, is_income: bool) -> str | None:
        counts, vocab = self._count[is_income], self._vocab[is_income]
        if len(counts) < 2:
            return None
        f = [x for x in _features(merchant, description) if x in vocab]
        if len(f) < 2:
            return None  # too little in common with anything sorted so far
        n, size = sum(counts.values()), len(vocab)
        scores = {
            category: math.log(k / n) + sum(
                math.log((self._features[(is_income, category)][x] + 1) / (self._totals[(is_income, category)] + size))
                for x in f
            )
            for category, k in counts.items()
        }
        best = max(scores, key=scores.get)
        top = scores[best]
        confidence = 1 / sum(math.exp(s - top) for s in scores.values())
        return best if confidence >= MIN_CONFIDENCE else None


class UnsortedSuggestions:
    """Suggestions for unsorted bookings (as shown in the review queue). The
    model is only built when a booking needs one."""

    def __init__(self, session: Session):
        self._session = session
        self._suggester: CategorySuggester | None = None

    def for_transaction(self, tx: Transaction) -> str | None:
        if tx.is_transfer or not (tx.category is None or tx.category in UNSORTED_CATEGORIES):
            return None
        self._suggester = self._suggester or CategorySuggester(self._session)
        raw = tx.raw_transaction
        return self._suggester.suggest(tx.merchant, raw.original_description if raw else tx.normalized_description,
                                       tx.transaction_type == TransactionType.INCOME)
