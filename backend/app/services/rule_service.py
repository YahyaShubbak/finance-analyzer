"""Turns a one-off transaction correction into a reusable, persisted rule
(spec Milestone 3, sections 3-4).

Priority is already enforced by the existing normalize_merchant/categorize
functions (app.normalization.merchant/category), which sort user-defined
rules ahead of built-in defaults — this module only needs to create rules
with is_user_defined=True and the two normalization functions already do
the right thing for every future import.

Which text of a booking a rule matches is worked out in
app.services.rule_patterns.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlmodel import Session, select

from app.config import settings
from app.db.models import (
    Account,
    AccountType,
    CategoryRule,
    MerchantRule,
    RawTransaction,
    Transaction,
    TransactionType,
    UserCorrection,
)

# (at import time, not when first used: importing it registers the SQL function fold() for
# every database connection opened from then on - _could_contain relies on it)
from app.db.session import fold_text
from app.i18n import tr
from app.normalization.category import (
    CARD_ACCOUNT_EXCLUDED,
    DEFAULT_CATEGORY_RULES,
    UNSORTED_CATEGORIES,
    categorize,
    rule_could_match,
    rule_matches,
)
from app.normalization.merchant import DEFAULT_MERCHANT_RULES, normalize_merchant
from app.normalization.review import compute_review_status
from app.services.category_memory import category_memory
from app.services.chains import chain_index, payee_name
from app.services.duplicate_preview_service import load_rules
from app.services.rule_patterns import (
    category_rule_source,
    derive_merchant_pattern,
    raw_counterparty,
    raw_extra,
)
from app.services.transfer_marking import sort_card_bill_payees


class RuleServiceError(Exception):
    pass


def _could_contain(pattern: str, *columns):
    """SQL condition: one of `columns` may contain the plain `pattern`
    (compared folded, as the search does). Never misses a row the pattern
    occurs in ignoring case — the exact check stays with the caller — so
    that only those rows are loaded, not every booking for every lesson.
    None when the pattern can't be searched for this way."""
    from sqlalchemy import func, or_

    if not pattern or "\n" in pattern:
        return None
    escaped = fold_text(pattern).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return or_(*(func.fold(column).like(f"%{escaped}%", escape="\\") for column in columns))


def create_merchant_rule_from_transaction(
    session: Session, transaction_id: int, normalized_merchant: str
) -> tuple[Transaction, MerchantRule, int]:
    """Returns the transaction, the rule, and how many similar transactions got the name too."""
    tx = session.get(Transaction, transaction_id)
    if tx is None:
        raise RuleServiceError(tr("Unknown transaction_id={transaction_id}", transaction_id=transaction_id))
    source_text = raw_counterparty(tx.raw_transaction) or (
        tx.raw_transaction.original_description if tx.raw_transaction else None
    )
    if not source_text:
        raise RuleServiceError(tr("Transaction has no original description to derive a rule from."))

    pattern = derive_merchant_pattern(source_text)

    # Reuse an existing identical user rule rather than creating a duplicate.
    existing = session.exec(
        select(MerchantRule).where(
            MerchantRule.pattern == pattern,
            MerchantRule.is_user_defined == True,  # noqa: E712
        )
    ).first()
    if existing is not None:
        existing.normalized_merchant = normalized_merchant
        rule = existing
    else:
        rule = MerchantRule(pattern=pattern, is_regex=False, normalized_merchant=normalized_merchant, is_user_defined=True)
        session.add(rule)

    old_merchant = tx.merchant
    tx.merchant = normalized_merchant
    if tx.needs_review:
        tx.needs_review = False
        tx.review_reason = None

    session.add(UserCorrection(
        transaction_id=tx.id, field="merchant",
        old_value=old_merchant, new_value=normalized_merchant,
    ))
    session.add(tx)
    session.flush()
    # like a learned category: similar existing transactions get the name now
    # (never one whose merchant the user set by hand)
    applied = _rename_matching(session, rule, skip_id=tx.id)
    session.commit()
    session.refresh(tx)
    session.refresh(rule)
    return tx, rule, applied


def _rename_matching(session: Session, rule: MerchantRule, skip_id: int) -> int:
    corrected = set(session.exec(select(UserCorrection.transaction_id, UserCorrection.field)).all())
    word = re.compile(rf"(?<!\w){re.escape(rule.pattern)}(?!\w)", re.IGNORECASE)
    changed = 0
    query = select(Transaction, RawTransaction).join(RawTransaction, RawTransaction.id == Transaction.raw_transaction_id)
    # the counterparty is read from the raw row's JSON, where a quote or backslash is written escaped
    if not any(ch in rule.pattern for ch in '"\\'):
        candidates = _could_contain(rule.pattern, RawTransaction.original_description, RawTransaction.extra_fields_json)
        if candidates is not None:
            query = query.where(candidates)
    for tx, raw in session.exec(query).all():
        if tx.id == skip_id or (tx.id, "merchant") in corrected or tx.merchant == rule.normalized_merchant:
            continue
        text = " ".join(filter(None, [raw_counterparty(raw), raw.original_description]))
        if not text or rule.pattern.lower() not in text.lower() or not word.search(text):
            continue
        tx.merchant = rule.normalized_merchant
        if (tx.id, "category") not in corrected and tx.transaction_type != TransactionType.TRANSFER:
            tx.needs_review, tx.review_reason = compute_review_status(tx.merchant, tx.category)
        session.add(tx)
        changed += 1
    return changed


# --- learning categories -------------------------------------------------------

@dataclass
class CategoryLesson:
    transaction: Transaction
    rule: CategoryRule | None  # None: nothing identifying to learn from, only this transaction changed
    applied_to: int            # other existing transactions whose category changed


def learn_category(session: Session, transaction_id: int, category: str,
                   leave_out: frozenset[int] | set[int] = frozenset()) -> CategoryLesson:
    """The user assigns `category` to a transaction: it is set (as a manual
    correction), and a rule is learned from the transaction's payee, which
    applies to future imports AND right away to similar existing
    transactions. Transactions the user corrected by hand are never changed."""
    tx = session.get(Transaction, transaction_id)
    if tx is None:
        raise RuleServiceError(tr("Unknown transaction_id={transaction_id}", transaction_id=transaction_id))

    match_field, _source = category_rule_source(tx)
    # a chain's branch ("MERCADONA C/JACA VALENCIA"): learned for the whole chain ("MERCADONA")
    pattern = payee_name(tx, chain_index(session))

    rule = None
    if pattern is not None:
        # Teaching the same pattern again replaces the lesson instead of piling up rules.
        rule = session.exec(
            select(CategoryRule).where(
                CategoryRule.pattern == pattern,
                CategoryRule.match_field == match_field,
                CategoryRule.is_user_defined == True,  # noqa: E712
            )
        ).first()
        if rule is not None:
            rule.category = category
        else:
            rule = CategoryRule(
                pattern=pattern, is_regex=False, match_field=match_field,
                category=category, priority=0, is_user_defined=True,
            )
        session.add(rule)

    old_category = tx.category
    tx.category = category
    if tx.needs_review:
        tx.needs_review = False
        tx.review_reason = None
    if old_category != category:
        session.add(UserCorrection(
            transaction_id=tx.id, field="category",
            old_value=old_category, new_value=category,
        ))
    session.add(tx)
    session.flush()

    # leave_out: bookings the user said don't belong (they stay to be checked)
    applied = recategorize_matching(session, rule, skip_ids={tx.id, *leave_out}) if rule is not None else 0
    session.commit()
    session.refresh(tx)
    if rule is not None:
        session.refresh(rule)
    return CategoryLesson(tx, rule, applied)


def recategorize_matching(session: Session, rule: CategoryRule, skip_ids: frozenset[int] | set[int] = frozenset(),
                          without_rule: bool = False) -> int:
    """Re-categorize the existing transactions `rule` matches with the current
    rule set (optionally as if `rule` did not exist). Manually corrected
    categories and transfers stay as they are. Returns how many changed."""
    _merchant_rules, category_rules = load_rules(session)
    if without_rule:
        category_rules = [r for r in category_rules if r.id != rule.id]
    card_account_ids = set(session.exec(select(Account.id).where(Account.account_type == AccountType.CREDIT_CARD)).all())
    corrected = set(session.exec(select(UserCorrection.transaction_id, UserCorrection.field)).all())

    changed = 0
    query = select(Transaction, RawTransaction).join(RawTransaction, RawTransaction.id == Transaction.raw_transaction_id)
    candidates = None if rule.is_regex else _could_contain(
        rule.pattern, Transaction.merchant, RawTransaction.original_description)
    if candidates is not None:
        query = query.where(candidates)
    rows = session.exec(query).all()
    for tx, raw in rows:
        if tx.id in skip_ids or (tx.id, "category") in corrected or tx.transaction_type == TransactionType.TRANSFER:
            continue
        if not rule_could_match(rule, f"{tx.merchant or ''}\n{raw.original_description or ''}".lower()) \
                or not rule_matches(rule, tx.merchant, raw.original_description, tx.amount_minor):
            continue
        category = categorize(
            tx.merchant, raw.original_description, tx.amount_minor, category_rules,
            is_income=tx.transaction_type == TransactionType.INCOME,
            exclude=CARD_ACCOUNT_EXCLUDED if tx.account_id in card_account_ids else frozenset(),
            merchant_category=raw_extra(raw, "_merchant_category"),
        )
        if category == tx.category:
            continue
        tx.category = category
        if (tx.id, "merchant") not in corrected:
            tx.needs_review, tx.review_reason = compute_review_status(tx.merchant, tx.category)
        session.add(tx)
        changed += 1
    return changed


@dataclass
class LearnedRule:
    rule: CategoryRule
    matching_transactions: int


def list_learned_category_rules(session: Session) -> list[LearnedRule]:
    rules = session.exec(
        select(CategoryRule).where(CategoryRule.is_user_defined == True)  # noqa: E712
        .order_by(CategoryRule.category, CategoryRule.pattern)
    ).all()
    rows = session.exec(
        select(Transaction.merchant, RawTransaction.original_description, Transaction.amount_minor)
        .join(RawTransaction, RawTransaction.id == Transaction.raw_transaction_id)
    ).all()
    texts = [f"{merchant or ''}\n{description or ''}".lower() for merchant, description, _amount in rows]
    return [
        LearnedRule(rule, sum(
            1 for (merchant, description, amount), text in zip(rows, texts, strict=True)
            if rule_could_match(rule, text) and rule_matches(rule, merchant, description, amount)
        ))
        for rule in rules
    ]


def forget_category_rule(session: Session, rule_id: int) -> int:
    """Deletes a learned rule; the transactions it categorized get the
    category the remaining rules give them (manual corrections stay).
    Returns how many transactions changed."""
    rule = session.get(CategoryRule, rule_id)
    if rule is None or not rule.is_user_defined:
        raise RuleServiceError(tr("Learned rule not found."))
    changed = recategorize_matching(session, rule, without_rule=True)
    session.delete(rule)
    session.commit()
    return changed


@dataclass
class ReapplyResult:
    transactions_checked: int
    merchants_changed: int
    categories_changed: int


def reapply_rules(session: Session) -> ReapplyResult:
    """Re-run merchant/category rules over ALL existing transactions — e.g.
    after creating rules, or after an update improved the built-in rules.
    A field the user corrected manually is never changed."""
    merchant_rules, category_rules = load_rules(session)
    card_account_ids = set(session.exec(select(Account.id).where(Account.account_type == AccountType.CREDIT_CARD)).all())
    corrected = set(session.exec(select(UserCorrection.transaction_id, UserCorrection.field)).all())

    rows = session.exec(
        select(Transaction, RawTransaction).join(RawTransaction, RawTransaction.id == Transaction.raw_transaction_id)
    ).all()
    memory = category_memory(session)
    merchants_changed = categories_changed = 0
    for tx, raw in rows:
        merchant_fixed = (tx.id, "merchant") in corrected
        category_fixed = (tx.id, "category") in corrected
        if not merchant_fixed:
            merchant = normalize_merchant(raw.original_description, merchant_rules, raw_counterparty(raw))
            if merchant != tx.merchant:
                tx.merchant = merchant
                merchants_changed += 1
        if not category_fixed and tx.transaction_type != TransactionType.TRANSFER:
            category = categorize(
                tx.merchant, raw.original_description, tx.amount_minor, category_rules,
                is_income=tx.transaction_type == TransactionType.INCOME,
                exclude=CARD_ACCOUNT_EXCLUDED if tx.account_id in card_account_ids else frozenset(),
                merchant_category=raw_extra(raw, "_merchant_category"),
            )
            if category in UNSORTED_CATEGORIES:
                category = memory.category_for(tx.merchant, tx.transaction_type == TransactionType.INCOME) or category
            if category != tx.category:
                tx.category = category
                categories_changed += 1
        if not (merchant_fixed or category_fixed) and tx.transaction_type != TransactionType.TRANSFER:
            tx.needs_review, tx.review_reason = compute_review_status(tx.merchant, tx.category)
        session.add(tx)
    session.commit()
    # the rules don't know a card's issuer: its unlinked bills are sorted again
    sort_card_bill_payees(session)
    return ReapplyResult(len(rows), merchants_changed, categories_changed)


#: raise when the way merchants are read changes (not only the rule lists): existing bookings are sorted again
NORMALIZATION_VERSION = 2
#: in the data folder: the rule version existing bookings were last sorted with
RULES_MARKER = ".rules_version"


def apply_rule_updates(session: Session) -> None:
    """On start-up: when the built-in rules changed since the last start
    (a new version), sort the transactions already imported again — never
    those the user sorted by hand. A failure here must never keep the app
    from starting."""
    import hashlib
    import logging

    logger = logging.getLogger("finance")
    version = hashlib.sha256(repr((DEFAULT_CATEGORY_RULES, DEFAULT_MERCHANT_RULES, NORMALIZATION_VERSION)).encode()).hexdigest()[:16]
    marker = settings.data_dir / RULES_MARKER
    try:
        if marker.exists() and marker.read_text(encoding="utf-8").strip() == version:
            return
        if session.exec(select(Transaction.id)).first() is not None:
            result = reapply_rules(session)
            logger.info("Built-in rules changed: %d categories updated", result.categories_changed)
        marker.write_text(version, encoding="utf-8")
    except Exception:  # noqa: BLE001 — logged; the rules apply to new imports anyway
        session.rollback()
        logger.exception("Could not apply the updated rules")
