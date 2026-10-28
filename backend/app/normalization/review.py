"""Deterministic "needs review" criteria (spec Milestone 3, section 5).

A transaction needs review when normalization genuinely couldn't confidently
place it — never as a blanket "every import needs checking" behavior.
Both conditions are simple, explainable, and rule-based (no ML/heuristics
beyond what merchant/category normalization already does):

* merchant is None — nothing could be extracted/normalized at all
* category is one of the two generic fallback buckets ("Other Expense" /
  "Other Income") — no specific category rule matched

Duplicates are deliberately excluded from this check by the caller — a
duplicate has its own distinct resolution path (accept/keep at import
time) and doesn't need to additionally clutter the review queue.
"""
from __future__ import annotations

from app.i18n import tr
from app.normalization.category import UNSORTED_CATEGORIES

# Stored in English (Transaction.review_reason) and translated when shown.
MERCHANT_UNCLEAR = "Merchant could not be confidently normalized."
CATEGORY_UNCLEAR = "Category could not be confidently determined."
REFUND_FROM_SOMEONE_ELSE = (
    "Paid onto the card from someone else's account, so counted as a refund."
    " Give it the category of the expense it repays."
)
REVIEW_REASONS = (MERCHANT_UNCLEAR, CATEGORY_UNCLEAR, REFUND_FROM_SOMEONE_ELSE)


def compute_review_status(merchant: str | None, category: str | None) -> tuple[bool, str | None]:
    if merchant is None:
        return True, MERCHANT_UNCLEAR
    if category is None or category in UNSORTED_CATEGORIES:
        return True, CATEGORY_UNCLEAR
    return False, None


def review_reason_text(reason: str | None) -> str | None:
    """A stored review reason in the current UI language."""
    return tr(reason) if reason else None
