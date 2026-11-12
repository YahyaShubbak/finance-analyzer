"""What becomes of a transaction's category and review flag when the app
recognizes it as money between the user's own accounts (a transfer pair,
the payment that settles a card statement) — and when that is undone.

A transfer is left out of income and expenses, so its category needs no
review: an unsorted one is filed under "Transfers". A category the user
chose is never changed. Released again, the transaction is sorted by the
rules like any other.
"""
from __future__ import annotations

import logging

from sqlmodel import Session, or_, select

from app.db.chunks import chunked
from app.db.models import Account, AccountType, RawTransaction, Transaction, TransactionType, UserCorrection
from app.normalization.category import CARD_ACCOUNT_EXCLUDED, UNSORTED_CATEGORIES, categorize
from app.normalization.review import REFUND_FROM_SOMEONE_ELSE, compute_review_status
from app.services.account_recognition import own_ibans_by_account
from app.services.chains import chain_index, payee_name
from app.services.duplicate_preview_service import is_card_payment, load_rules, paid_by_someone_else
from app.services.rule_patterns import raw_extra

logger = logging.getLogger("finance")

TRANSFERS = "Transfers"
# A card bill linked to its card is money between own accounts, too.
_UNSORTED = {None, *UNSORTED_CATEGORIES, "Card bills"}


def corrected_fields(session: Session, tx_ids: list[int] | None = None) -> set[tuple[int, str]]:
    stmt = select(UserCorrection.transaction_id, UserCorrection.field)
    if tx_ids is None:
        return set(session.exec(stmt).all())
    return {row for chunk in chunked(tx_ids) for row in session.exec(stmt.where(UserCorrection.transaction_id.in_(chunk))).all()}


def natural_type(amount_minor: int) -> TransactionType:
    return TransactionType.INCOME if amount_minor > 0 else TransactionType.EXPENSE


def manually_corrected_type_ids(session: Session) -> set[int]:
    return set(
        session.exec(select(UserCorrection.transaction_id).where(UserCorrection.field == "transaction_type")).all()
    )


def settle_as_transfer(tx: Transaction, corrected: set[tuple[int, str]]) -> None:
    if (tx.id, "category") not in corrected and tx.category in _UNSORTED:
        tx.category = TRANSFERS
    tx.needs_review, tx.review_reason = False, None


def release_from_transfer(session: Session, tx: Transaction, corrected: set[tuple[int, str]],
                          category_rules: list | None = None) -> None:
    """`tx` is an ordinary transaction again (type already reset)."""
    if (tx.id, "category") not in corrected and tx.category == TRANSFERS:
        raw = session.get(RawTransaction, tx.raw_transaction_id)
        account = session.get(Account, tx.account_id)
        if category_rules is None:
            _merchant_rules, category_rules = load_rules(session)
        tx.category = categorize(
            tx.merchant, raw.original_description if raw else tx.normalized_description, tx.amount_minor,
            category_rules, is_income=tx.transaction_type == TransactionType.INCOME,
            exclude=CARD_ACCOUNT_EXCLUDED if account and account.account_type == AccountType.CREDIT_CARD else frozenset(),
            merchant_category=raw_extra(raw, "_merchant_category") if raw else None,
        )
    if (tx.id, "category") not in corrected and (tx.id, "merchant") not in corrected:
        tx.needs_review, tx.review_reason = compute_review_status(tx.merchant, tx.category)


def unpair_transfer(session: Session, tx: Transaction) -> None:
    """Revert the partner of an auto-detected transfer pair when one half
    is corrected manually or deleted, so no half-transfer is left behind.
    The partner itself is not manually corrected, so a later re-scan may
    pair it again with a better match."""
    if tx.transfer_pair_id is None:
        return
    partner = session.get(Transaction, tx.transfer_pair_id)
    tx.transfer_pair_id = None
    if partner is not None and partner.transfer_pair_id == tx.id:
        partner.transfer_pair_id = None
        account = session.get(Account, partner.account_id)
        if not (account and account.account_type == AccountType.CREDIT_CARD and partner.amount_minor > 0):
            # (a payment onto a card stays a transfer, just unpaired)
            partner.is_transfer = False
            partner.transaction_type = natural_type(partner.amount_minor)
            release_from_transfer(session, partner, corrected_fields(session, [partner.id]))
        session.add(partner)


def settle_flagged_transfers(session: Session) -> None:
    """On start-up: transfers recognized by older versions still asked for a
    category review, and card bills that are no transfer were filed under
    "Transfers" (an expense listed as a transfer). A failure here must never
    keep the app from starting."""
    try:
        misfiled = session.exec(
            select(Transaction).where(Transaction.is_transfer == False, Transaction.category == TRANSFERS)  # noqa: E712
        ).all()
        if misfiled:
            corrected = corrected_fields(session, [t.id for t in misfiled])
            _merchant_rules, category_rules = load_rules(session)
            for tx in misfiled:
                release_from_transfer(session, tx, corrected, category_rules)
                session.add(tx)
            session.commit()
        flagged = session.exec(
            select(Transaction).where(Transaction.is_transfer == True, Transaction.needs_review == True)  # noqa: E712
        ).all()
        if not flagged:
            return
        corrected = corrected_fields(session, [t.id for t in flagged])
        for tx in flagged:
            settle_as_transfer(tx, corrected)
            session.add(tx)
        session.commit()
        logger.info("Cleared the category review of %d transfers", len(flagged))
    except Exception:  # noqa: BLE001 — logged; only the review queue is affected
        session.rollback()
        logger.exception("Could not clear the category review of transfers")


def retype_card_payments(session: Session) -> int:
    """Money in on a card that pays the card off, read as a refund by an
    older version (e.g. a bare "Payment" line): a transfer, so transfer
    detection can pair it with the bank's debit. And the other way round:
    money from someone else's account, read as a card payment, is a refund
    for the user to sort. A type the user set stays."""
    cards = {a.id: a for a in session.exec(select(Account).where(Account.account_type == AccountType.CREDIT_CARD)).all()}
    if not cards:
        return 0
    chosen = manually_corrected_type_ids(session)
    own_ibans = own_ibans_by_account(session)
    rows = session.exec(
        select(Transaction, RawTransaction).join(RawTransaction, RawTransaction.id == Transaction.raw_transaction_id)
        .where(Transaction.account_id.in_(list(cards)), Transaction.amount_minor > 0)
    ).all()
    corrected = corrected_fields(session, [tx.id for tx, _raw in rows])
    retyped = 0
    for tx, raw in rows:
        if tx.id in chosen:
            continue
        texts = [raw.original_description or tx.normalized_description, raw_extra(raw, "_booking_text")]
        iban = raw_extra(raw, "_counterparty_iban")
        if tx.transaction_type == TransactionType.TRANSFER:
            if (tx.transfer_pair_id is None and tx.settles_statement_id is None
                    and paid_by_someone_else(tx.account_id, texts, iban, own_ibans)):
                tx.transaction_type, tx.is_transfer = TransactionType.EXPENSE, False  # a refund
                release_from_transfer(session, tx, corrected)
                if (tx.id, "category") not in corrected:
                    tx.needs_review, tx.review_reason = True, REFUND_FROM_SOMEONE_ELSE
                session.add(tx)
                retyped += 1
        elif is_card_payment(cards[tx.account_id], tx.amount_minor, texts[:1], iban, own_ibans):
            tx.transaction_type, tx.is_transfer = TransactionType.TRANSFER, True
            settle_as_transfer(tx, corrected)
            session.add(tx)
            retyped += 1
    session.commit()
    return retyped


def sort_card_bill_payees(session: Session) -> int:
    """A payee that has paid a card's statement before is the card's issuer:
    its other debits are card bills too — also for months whose statement
    isn't imported ("LANDESBANK BERLIN ... RECHNUNG VOM ..."), where they
    can't be linked. Only unsorted bookings are changed, never ones sorted
    by hand. Returns how many were sorted."""
    chains = chain_index(session)

    def payee(tx: Transaction) -> str | None:
        name = payee_name(tx, chains)
        return name.upper() if name else None

    issuers = {payee(tx) for tx in session.exec(
        select(Transaction).where(Transaction.settles_statement_id != None)  # noqa: E711
    ).all()} - {None}
    if not issuers:
        return 0
    card_accounts = set(session.exec(select(Account.id).where(Account.account_type == AccountType.CREDIT_CARD)).all())
    corrected = corrected_fields(session)
    sorted_count = 0
    for tx in session.exec(select(Transaction).where(
        Transaction.amount_minor < 0, Transaction.is_transfer == False,  # noqa: E712
        Transaction.is_duplicate == False,  # noqa: E712
        # (SQL: "IN (..., NULL)" never matches a missing category)
        or_(Transaction.category == "Other Expense", Transaction.category.is_(None)),
    )).all():
        if tx.account_id in card_accounts or (tx.id, "category") in corrected or payee(tx) not in issuers:
            continue
        tx.category = "Card bills"
        if (tx.id, "merchant") not in corrected:
            tx.needs_review, tx.review_reason = compute_review_status(tx.merchant, tx.category)
        session.add(tx)
        sorted_count += 1
    session.commit()
    return sorted_count
