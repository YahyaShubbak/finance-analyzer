"""Wires app.normalization.transfers' pure pairing logic into the actual
data pipeline. Two modes:

* **Incremental** (`full_rescan=False`, the default) — runs after every
  import commit, limited to the imported date range. Only considers
  transactions not already marked as a transfer, so existing matches are
  left alone.

* **Full re-scan** (`full_rescan=True`) — explicitly re-evaluates every
  eligible transaction from scratch, including ones a previous
  incremental run already paired. This makes the overall system safe
  against import-order dependence: incremental detection alone can match
  a transaction unambiguously simply because its true (later-to-be
  ambiguous) competitor hadn't been imported yet.

Design constraints:
* Credit-card <-> bank-payment matching of card STATEMENTS is the
  reconciliation engine's job; its settlements are recognizable by
  `settles_statement_id` and never touched here. Card accounts without
  statements (spreadsheet exports, account-style PDFs of cards with an
  IBAN) take part with their payments only: money in that was already
  recognized as the card being paid or topped up (never a refund).
* Skips any transaction whose type was ever manually corrected by the
  user (tracked via UserCorrection) — automatic detection must never
  overwrite a human's explicit judgment call.
* A full re-scan is idempotent: it resets auto-matched pairs and
  re-derives them from the current data.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, select

from app.db.chunks import chunked
from app.db.models import (
    Account,
    AccountType,
    RawTransaction,
    Transaction,
    TransactionType,
    UserCorrection,
)
from app.normalization.transfers import DEFAULT_MAX_DAY_GAP, TransferCandidate, find_transfer_pairs
from app.services.transfer_marking import corrected_fields, release_from_transfer, settle_as_transfer


@dataclass
class TransferDetectionResult:
    transactions_considered: int
    pairs_matched: int
    transactions_marked_as_transfer: int
    transactions_reverted_to_ordinary: int  # only nonzero for full_rescan


def natural_type(amount_minor: int) -> TransactionType:
    return TransactionType.INCOME if amount_minor > 0 else TransactionType.EXPENSE


def manually_corrected_type_ids(session: Session) -> set[int]:
    return set(
        session.exec(select(UserCorrection.transaction_id).where(UserCorrection.field == "transaction_type")).all()
    )


def _counterparty_ibans(session: Session, tx_ids: list[int], own_ibans: set[str] | None = None) -> dict[int, str]:
    """The counterparty IBAN of each transaction: from its own column, or —
    when the statement prints it only in the booking text (e.g. comdirect)
    — an IBAN of one of the user's own accounts named there."""
    from app.services.account_recognition import _IBAN_RE, _valid_iban

    result: dict[int, str] = {}
    if not tx_ids:
        return result
    rows = [
        row for chunk in chunked(tx_ids)
        for row in session.exec(
            select(Transaction.id, RawTransaction.extra_fields_json, RawTransaction.original_description)
            .join(RawTransaction, RawTransaction.id == Transaction.raw_transaction_id)
            .where(Transaction.id.in_(chunk))
        ).all()
    ]
    for tx_id, extra_json, description in rows:
        try:
            extra = json.loads(extra_json) if extra_json else {}
        except ValueError:
            extra = {}
        iban = extra.get("_counterparty_iban") if isinstance(extra, dict) else None
        if not iban and own_ibans:
            text = " ".join(filter(None, [description, extra.get("_details") if isinstance(extra, dict) else None]))
            named = {v for m in _IBAN_RE.finditer(text) if (v := _valid_iban(m.group(0)))} & own_ibans
            iban = next(iter(named)) if len(named) == 1 else None
        if iban:
            result[tx_id] = iban
    return result


def run_transfer_detection(
    session: Session,
    max_day_gap: int = DEFAULT_MAX_DAY_GAP,
    full_rescan: bool = False,
    date_window: tuple[date, date] | None = None,
) -> TransferDetectionResult:
    accounts = session.exec(select(Account).where(Account.account_type != AccountType.CREDIT_CARD)).all()
    if not accounts:
        return TransferDetectionResult(0, 0, 0, 0)
    card_accounts = session.exec(select(Account).where(Account.account_type == AccountType.CREDIT_CARD)).all()
    account_ibans = {a.id: a.iban for a in [*accounts, *card_accounts] if a.iban}

    manually_corrected_ids = manually_corrected_type_ids(session)

    stmt = select(Transaction).where(
        Transaction.account_id.in_([a.id for a in accounts]),
        Transaction.is_duplicate == False,  # noqa: E712
        Transaction.settles_statement_id == None,  # noqa: E711 — owned by reconciliation
    )
    if date_window is not None and not full_rescan:
        stmt = stmt.where(Transaction.transaction_date >= date_window[0], Transaction.transaction_date <= date_window[1])
    in_scope = [t for t in session.exec(stmt).all() if t.id not in manually_corrected_ids]

    corrected = corrected_fields(session)
    reverted = 0
    if full_rescan:
        from app.services.duplicate_preview_service import load_rules

        _merchant_rules, category_rules = load_rules(session)
        for t in in_scope:
            if t.is_transfer and t.transfer_pair_id is not None:
                t.is_transfer = False
                t.transfer_pair_id = None
                t.transaction_type = natural_type(t.amount_minor)
                release_from_transfer(session, t, corrected, category_rules)
                session.add(t)
                reverted += 1
        # Anything else still marked as a transfer (manually, without a
        # pair) stays untouched.
    eligible = [t for t in in_scope if not t.is_transfer]
    card_payments = _statementless_card_payments(session, card_accounts, manually_corrected_ids, full_rescan, date_window)
    eligible += card_payments

    if len(eligible) < 2:
        if reverted:
            session.commit()
        return TransferDetectionResult(len(eligible), 0, 0, reverted)

    ibans = _counterparty_ibans(session, [t.id for t in eligible], set(account_ibans.values())) if account_ibans else {}
    candidates = [
        TransferCandidate(
            id=t.id, account_id=t.account_id, transaction_date=t.transaction_date, amount_minor=t.amount_minor,
            currency=t.currency, counterparty_iban=ibans.get(t.id),
        )
        for t in eligible
    ]
    pairs = find_transfer_pairs(candidates, max_day_gap=max_day_gap, account_ibans=account_ibans)

    tx_by_id = {t.id: t for t in eligible}
    card_payment_ids = {t.id for t in card_payments}
    pairs = [(a, b) for a, b in pairs if not (a in card_payment_ids and b in card_payment_ids)]
    for id_a, id_b in pairs:
        tx_a, tx_b = tx_by_id[id_a], tx_by_id[id_b]
        for tx, partner in ((tx_a, tx_b), (tx_b, tx_a)):
            tx.is_transfer = True
            tx.transaction_type = TransactionType.TRANSFER
            tx.transfer_pair_id = partner.id
            settle_as_transfer(tx, corrected)
            session.add(tx)

    if pairs or reverted:
        session.commit()

    return TransferDetectionResult(len(eligible), len(pairs), 2 * len(pairs), reverted)


def detect_and_mark_transfers(
    session: Session,
    max_day_gap: int = DEFAULT_MAX_DAY_GAP,
    date_window: tuple[date, date] | None = None,
) -> int:
    """Incremental entry point, used by the import pipeline after every
    commit. Returns the number of transactions newly marked as transfers."""
    result = run_transfer_detection(session, max_day_gap=max_day_gap, full_rescan=False, date_window=date_window)
    return result.transactions_marked_as_transfer


def _statementless_card_payments(
    session: Session, card_accounts: list[Account], manually_corrected_ids: set[int], full_rescan: bool,
    date_window: tuple[date, date] | None,
) -> list[Transaction]:
    """Payments onto card accounts (typed as transfers when imported): from
    exports, and the "payment received" lines of statements — such a line
    pays the PREVIOUS statement, which may not be imported. (If it is, its
    reconciliation claims the bank debit, taking it from this pairing.)
    A full re-scan releases their earlier pairings so they can be matched afresh."""
    if not card_accounts:
        return []
    stmt = select(Transaction).where(
        Transaction.account_id.in_([a.id for a in card_accounts]),
        Transaction.amount_minor > 0,
        Transaction.transaction_type == TransactionType.TRANSFER,
        Transaction.is_duplicate == False,  # noqa: E712
        Transaction.settles_statement_id == None,  # noqa: E711
    )
    if date_window is not None and not full_rescan:
        stmt = stmt.where(Transaction.transaction_date >= date_window[0], Transaction.transaction_date <= date_window[1])
    result = []
    for tx in session.exec(stmt).all():
        if tx.id in manually_corrected_ids:
            continue
        if tx.transfer_pair_id is not None:
            if not full_rescan:
                continue
            tx.transfer_pair_id = None
            session.add(tx)
        result.append(tx)
    return result


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
