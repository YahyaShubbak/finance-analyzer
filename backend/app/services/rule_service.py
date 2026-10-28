"""Turns a one-off transaction correction into a reusable, persisted rule
(spec Milestone 3, sections 3-4).

Priority is already enforced by the existing normalize_merchant/categorize
functions (app.normalization.merchant/category), which sort user-defined
rules ahead of built-in defaults — this module only needs to create rules
with is_user_defined=True and the two normalization functions already do
the right thing for every future import.

Pattern derivation for merchant rules deliberately strips the
transaction-specific noise (trailing order/reference codes) so a rule
generalizes to future variants of the same merchant (e.g.
"AMZN Mktp DE*AB1234" -> pattern "AMZN Mktp DE", matching a future
"AMZN Mktp DE*XY9876" too) while staying a plain substring match — no
regex required, fully explainable. It never strips so much that only a
payment processor or booking type remains ("PAYPAL *NETFLIX.COM" must not
become "PAYPAL", which would rename every future PayPal payment).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlmodel import Session, select

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
from app.i18n import tr
from app.normalization.category import UNSORTED_CATEGORIES

# "*AB1234" — a code containing a digit. "*NETFLIX.COM" (no digit) is the
# actual merchant behind a payment processor and is kept.
_TRAILING_CODE_RE = re.compile(r"\*(?=\S*\d)\S+$")
# A whitespace-separated trailing numeric token of 2+ digits is almost
# always a transaction/order/reference number, not part of the merchant
# name itself (the whitespace requirement avoids stripping something like
# "Store24", where the digits are fused to the name).
_TRAILING_DIGITS_RE = re.compile(r"\s+\d{2,}\s*$")


class RuleServiceError(Exception):
    pass


# Words that say HOW something was paid, not WHO was paid.
_GENERIC_WORDS = {
    "paypal", "sepa", "lastschrift", "kartenzahlung", "karte", "ueberweisung", "überweisung", "gutschrift",
    "dauerauftrag", "visa", "mastercard", "girocard", "debit", "card", "payment", "zahlung", "einkauf",
    "pos", "online", "purchase", "basislastschrift", "folgelastschrift", "sumup", "zettle", "google", "apple",
    "pay", "ref", "eref", "mref", "svwz", "gmbh", "und", "the",
}
MIN_PATTERN_LENGTH = 4


def derive_merchant_pattern(original_description: str) -> str:
    original = original_description.strip()
    text = _TRAILING_CODE_RE.sub("", original)
    text = _TRAILING_DIGITS_RE.sub("", text)
    text = text.strip(" -*#")
    meaningful = [w for w in re.findall(r"[a-zäöüß]+", text.lower()) if len(w) >= 3 and w not in _GENERIC_WORDS]
    if len(text) < MIN_PATTERN_LENGTH or not meaningful:
        # Too little left to identify the merchant -> use the full text,
        # which only matches this very specific description.
        return original
    return text


def raw_extra(raw: RawTransaction | None, key: str) -> str | None:
    if raw is None or not raw.extra_fields_json:
        return None
    try:
        return json.loads(raw.extra_fields_json).get(key)
    except (ValueError, AttributeError):
        return None


def raw_counterparty(raw: RawTransaction | None) -> str | None:
    return raw_extra(raw, "_counterparty")


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
    from app.normalization.review import compute_review_status

    corrected = set(session.exec(select(UserCorrection.transaction_id, UserCorrection.field)).all())
    word = re.compile(rf"(?<!\w){re.escape(rule.pattern)}(?!\w)", re.IGNORECASE)
    changed = 0
    for tx, raw in session.exec(
        select(Transaction, RawTransaction).join(RawTransaction, RawTransaction.id == Transaction.raw_transaction_id)
    ).all():
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

# Leading words that name the booking type, not the payee:
# "Lastschrift / Belastung REWE Markt GmbH ..." -> "REWE Markt GmbH ...".
_BOOKING_TYPE_WORDS = {
    "lastschrift", "belastung", "gutschrift", "überweisung", "ueberweisung", "sepa", "sepa-lastschrift",
    "sepa-überweisung", "sepa-ueberweisung", "sepa-gutschrift", "dauerauftrag", "kartenzahlung", "kartenumsatz",
    "kartenverfügung", "girocard", "debitkarte", "basislastschrift", "folgelastschrift", "erstlastschrift",
    "echtzeitüberweisung", "echtzeit-überweisung", "onlineüberweisung", "online-überweisung", "abbuchung",
    "einzug", "zahlungseingang", "zahlungsausgang", "übertrag", "uebertrag", "umbuchung", "storno",
    "rücklastschrift", "ruecklastschrift", "an", "von", "bei", "zugunsten", "auftraggeber",
    "empfänger", "empfaenger", "payment", "purchase", "card", "pos",
}
# Where the payee's name ends and booking details begin.
_STOP_WORDS = {
    "vom", "am", "datum", "ref", "ref.", "referenz", "kundenreferenz", "mandatsreferenz", "mandat", "nr", "nr.",
    "nummer", "rechnung", "rechnungsnr", "beleg", "kundennr", "iban", "bic", "iban:", "bic:", "eur", "euro",
    "januar", "februar", "märz", "maerz", "april", "mai", "juni", "juli", "august", "september", "oktober",
    "november", "dezember", "jan", "feb", "mär", "apr", "jun", "jul", "aug", "sep", "sept", "okt", "nov", "dez",
    "january", "february", "march", "may", "june", "july", "october", "december", "oct", "dec",
}
# SEPA field markers, also when printed with a space before the "+" ("EREF + ...").
_SEPA_MARKERS = {"eref", "mref", "kref", "svwz", "abwa", "abwe", "cred", "purp", "bref", "debt", "iban", "bic"}
_STOP_PREFIXES = tuple(f"{marker}+" for marker in _SEPA_MARKERS) + ("end-to-end",)
# Legal forms and fill words: never enough on their own to name a payee
# ("PayPal Europe S.a.r.l. et Cie" must not become a rule for all PayPal payments).
_NON_IDENTIFYING = _GENERIC_WORDS | {
    "europe", "sarl", "cie", "sca", "ltd", "inc", "llc", "kg", "ag", "se", "co", "ohg", "ug", "mbh", "klarna",
    "stripe", "adyen", "einkauf", "kauf", "danke", "vielen", "dank", "ihr", "ihre", "fuer", "für",
    "übertrag", "uebertrag", "umbuchung", "storno",
} | _SEPA_MARKERS
_MAX_PATTERN_WORDS = 5


def _identifying_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zäöüß]+", text.lower()) if len(w) >= 3 and w not in _NON_IDENTIFYING]


def derive_category_pattern(text: str) -> str | None:
    """The part of a merchant/description that names WHO was paid, so a
    learned category also fits the next booking with that payee:
    "Lastschrift / Belastung REWE Markt GmbH Einkauf 12,34 EUR vom 01.09."
    -> "REWE Markt GmbH". Booking type, amounts, dates, month names and
    reference codes are left out. The result is always a substring of
    `text` — or None when nothing in it identifies a payee (e.g. a bare
    "PayPal Europe S.a.r.l." line: every PayPal payment looks like that, so
    a rule would give all of them this one category)."""
    original = text.strip()
    tokens = list(re.finditer(r"\S+", original))
    start = 0
    while start < len(tokens):
        word = tokens[start].group().lower().strip(":,")
        if word in _BOOKING_TYPE_WORDS or not re.search(r"\w", word):
            start += 1
        elif start + 1 < len(tokens) and len(tokens[start + 1].group()) == 1 \
                and word + tokens[start + 1].group().lower() in _BOOKING_TYPE_WORDS:
            start += 2  # a booking word broken over two lines: "KARTENVERFÜGUN G"
        else:
            break
    kept = []
    for token in tokens[start:]:
        word = token.group().lower()
        if (any(ch.isdigit() for ch in word) or word.strip(",.;:+") in _STOP_WORDS | _SEPA_MARKERS
                or word.startswith(_STOP_PREFIXES) or word == "+"):
            break
        if kept and word.endswith(":"):
            break  # a field label ("Verwendungszweck:") ends the name
        kept.append(token)
        if len(kept) == _MAX_PATTERN_WORDS:
            break
    while kept and not _identifying_words(kept[-1].group()):
        kept.pop()  # trailing "Einkauf", "GmbH,", "/" ...
    # keep a legal form right after the name ("REWE Markt GmbH")
    if kept:
        following = tokens.index(kept[-1]) + 1
        if following < len(tokens) and len(kept) < _MAX_PATTERN_WORDS \
                and tokens[following].group().lower().strip(",.") in {"gmbh", "ag", "kg", "se", "ug", "ohg", "e.v."}:
            kept.append(tokens[following])
    if not kept:
        return None
    pattern = original[kept[0].start():kept[-1].end()].rstrip(",;:/-")
    if len(pattern) < MIN_PATTERN_LENGTH or not _identifying_words(pattern):
        return None
    return pattern


def category_rule_source(tx: Transaction) -> tuple[str, str]:
    """(match_field, text the pattern is derived from)."""
    if tx.merchant:
        return "merchant", tx.merchant
    return "description", tx.normalized_description or ""


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

    from app.services.chains import chain_index, payee_name

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
    from app.normalization.category import CARD_ACCOUNT_EXCLUDED, categorize, rule_could_match, rule_matches
    from app.normalization.review import compute_review_status
    from app.services.duplicate_preview_service import load_rules

    _merchant_rules, category_rules = load_rules(session)
    if without_rule:
        category_rules = [r for r in category_rules if r.id != rule.id]
    card_account_ids = set(session.exec(select(Account.id).where(Account.account_type == AccountType.CREDIT_CARD)).all())
    corrected = set(session.exec(select(UserCorrection.transaction_id, UserCorrection.field)).all())

    changed = 0
    rows = session.exec(
        select(Transaction, RawTransaction).join(RawTransaction, RawTransaction.id == Transaction.raw_transaction_id)
    ).all()
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
    from app.normalization.category import rule_could_match, rule_matches

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
    from app.normalization.category import CARD_ACCOUNT_EXCLUDED, categorize
    from app.normalization.merchant import normalize_merchant
    from app.normalization.review import compute_review_status
    from app.services.duplicate_preview_service import load_rules

    merchant_rules, category_rules = load_rules(session)
    card_account_ids = set(session.exec(select(Account.id).where(Account.account_type == AccountType.CREDIT_CARD)).all())
    corrected = set(session.exec(select(UserCorrection.transaction_id, UserCorrection.field)).all())

    rows = session.exec(
        select(Transaction, RawTransaction).join(RawTransaction, RawTransaction.id == Transaction.raw_transaction_id)
    ).all()
    from app.services.category_memory import CategoryMemory

    memory = CategoryMemory(session)
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
    from app.services.transfer_marking import sort_card_bill_payees

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

    from app.config import settings
    from app.normalization.category import DEFAULT_CATEGORY_RULES
    from app.normalization.merchant import DEFAULT_MERCHANT_RULES

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
