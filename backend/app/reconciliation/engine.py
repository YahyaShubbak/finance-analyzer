"""Credit-card reconciliation engine.

Three-level model:

    individual CC transactions -> credit-card statement -> bank account debit

Two independent discrepancies are tracked, because they have different
causes:

* transactions vs. statement  (e.g. a missing/duplicate line item)
* statement vs. bank debit    (e.g. a partial payment, or a fee applied
  at settlement that isn't itemized as a transaction)

The bank payment that settles a statement is excluded from income/expense
totals (the card transactions are the real expenses), so linking the
wrong transaction silently deletes a real expense. Therefore:

* Reading never writes. `compute_reconciliation` is side-effect free and
  is what every GET endpoint uses; only explicit actions (an import,
  choosing/clearing the payment, resolving) persist via
  `reconcile_statement`.
* A payment is only linked automatically when it is unambiguous and
  exact (same amount, same currency, not claimed or corrected by the
  user) and not already sorted as a purchase (a category other than
  "Card bills"/"Transfers"/unsorted). Near matches, and exact ones that
  are known purchases, are merely *suggested* for the user to confirm.
* Unlinking a payment (choosing another, clearing it, deleting the
  statement) restores the transaction to an ordinary expense.

Explanations are only ever proposed when the numbers actually support
them — never invented.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta

from sqlmodel import Session, func, select

from app.db.chunks import chunked
from app.db.models import (
    Account,
    AccountType,
    CreditCardStatement,
    RawTransaction,
    Reconciliation,
    ReconciliationStatus,
    Transaction,
    TransactionType,
    utcnow,
)
from app.i18n import tr
from app.normalization.category import UNSORTED_CATEGORIES

DEFAULT_BANK_MATCH_DAY_WINDOW = 15
# A card's direct debit comes on its due date, often two to three weeks after
# the statement (Bank Norwegian: 15 days after the statement date, later at
# weekends). Exactly the statement's amount, and the only such debit, is
# linked without asking up to this many days after the period's end.
AUTO_MATCH_MAX_DAY_GAP = 25
_WINDOW_DAYS_BEFORE_PERIOD_END = 5
# Suggestions (never auto-linked) may differ by up to 10 % or 10.00.
SUGGESTION_MAX_GAP_RATIO = 0.10
SUGGESTION_MAX_GAP_MINOR = 1000
# A bill paid late (holidays, a manual transfer) is still suggested when it is exactly the amount.
SUGGESTION_MAX_DAY_GAP = 40
# Categories of a bank debit that pays a card bill (see app.normalization.category).
CARD_BILL_CATEGORIES = frozenset({"Card bills", "Transfers"})


class ReconciliationError(Exception):
    pass


# ---------------------------------------------------------------------------
# Core computation (read-only)
# ---------------------------------------------------------------------------

def statement_transaction_ids(session: Session, statement: CreditCardStatement) -> set[int]:
    """The card transactions a statement lists: those imported from it, plus
    those it listed but that had already been imported from another file
    (e.g. the card's CSV export) — its rows were skipped as duplicates and
    point to them (raw extra field "_duplicate_of")."""
    rows = session.exec(
        select(RawTransaction.id, RawTransaction.extra_fields_json).where(RawTransaction.import_id == statement.import_id)
    ).all()
    ids = set(session.exec(
        select(Transaction.id).where(Transaction.raw_transaction_id.in_(
            select(RawTransaction.id).where(RawTransaction.import_id == statement.import_id)
        ))
    ).all()) if rows else set()
    for _raw_id, extra_json in rows:
        if extra_json and '"_duplicate_of"' in extra_json:
            duplicate_of = json.loads(extra_json).get("_duplicate_of")
            if isinstance(duplicate_of, int):
                ids.add(duplicate_of)
    # its own rows that were merged into the same booking from another file (twin_merge): that one counts
    for chunk in chunked(list(ids)):
        ids |= {kept for kept in session.exec(select(Transaction.duplicate_of_id).where(
            Transaction.id.in_(chunk), Transaction.is_duplicate == True,  # noqa: E712
            Transaction.duplicate_of_id != None,  # noqa: E711
        )).all()}
    return ids


def compute_transaction_total_minor(session: Session, statement: CreditCardStatement) -> int:
    """Total amount charged, as a positive integer, from the individual CC
    transactions belonging to this statement (expenses negative, refunds
    positive -> negated sum). Payment lines on the statement (the card
    being paid off) are transfers, not charges, and are excluded."""
    ids = statement_transaction_ids(session, statement)
    if not ids:
        return 0
    total = sum(
        session.exec(
            select(func.coalesce(func.sum(Transaction.amount_minor), 0))
            .where(
                Transaction.id.in_(chunk),
                Transaction.account_id == statement.account_id,
                Transaction.is_duplicate == False,  # noqa: E712
                Transaction.is_transfer == False,  # noqa: E712
            )
        ).one()
        for chunk in chunked(ids)
    )
    return -int(total)


def _claimed_payment_ids(session: Session, exclude_statement_id: int | None = None) -> set[int]:
    stmt = select(Transaction.id).where(Transaction.settles_statement_id != None)  # noqa: E711
    if exclude_statement_id is not None:
        stmt = stmt.where(Transaction.settles_statement_id != exclude_statement_id)
    return set(session.exec(stmt).all())


def find_candidate_bank_debits(
    session: Session,
    statement: CreditCardStatement,
    max_day_gap: int = DEFAULT_BANK_MATCH_DAY_WINDOW,
) -> list[tuple[Transaction, tuple[int, int]]]:
    """Every plausible bank payment for this statement, as
    (transaction, (amount_gap, date_gap)) sorted best-first."""
    if not statement.statement_total_minor or statement.statement_period_end is None:
        return []  # no amount, or nothing owed (a credit balance): no debit to look for

    from app.services.transfer_detection_service import manually_corrected_type_ids

    window_start = statement.statement_period_end - timedelta(days=_WINDOW_DAYS_BEFORE_PERIOD_END)
    window_end = statement.statement_period_end + timedelta(days=max(max_day_gap, SUGGESTION_MAX_DAY_GAP))
    bank_accounts = session.exec(select(Account.id).where(Account.account_type != AccountType.CREDIT_CARD)).all()
    if not bank_accounts:
        return []

    candidates = session.exec(
        select(Transaction).where(
            Transaction.account_id.in_(bank_accounts),
            Transaction.transaction_date >= window_start,
            Transaction.transaction_date <= window_end,
            Transaction.amount_minor < 0,
            Transaction.currency == statement.currency,
            Transaction.is_duplicate == False,  # noqa: E712
        )
    ).all()

    claimed = _claimed_payment_ids(session, exclude_statement_id=statement.id)
    corrected = manually_corrected_type_ids(session)
    max_gap = max(SUGGESTION_MAX_GAP_MINOR, round(SUGGESTION_MAX_GAP_RATIO * statement.statement_total_minor))

    scored: list[tuple[Transaction, tuple[int, int]]] = []
    for tx in candidates:
        if tx.id in claimed or (tx.id in corrected and tx.settles_statement_id != statement.id):
            continue
        if tx.is_transfer and tx.settles_statement_id != statement.id and not _pays_onto(session, tx, statement):
            continue  # a transfer of another kind (to another own account, or marked by the user)
        amount_gap = abs(abs(tx.amount_minor) - statement.statement_total_minor)
        date_gap = abs((tx.transaction_date - statement.statement_period_end).days)
        looks_like_bill = tx.is_transfer or tx.category in CARD_BILL_CATEGORIES
        if amount_gap and not looks_like_bill:
            continue  # an ordinary purchase is only a candidate at exactly the statement amount
        partial = abs(tx.amount_minor) < statement.statement_total_minor and looks_like_bill
        if amount_gap > max_gap and not partial:
            continue  # (a partial payment of a card bill is still worth suggesting)
        if date_gap > max_day_gap and amount_gap:
            continue  # later than the usual window: only exactly the statement amount
        scored.append((tx, (amount_gap, date_gap)))

    scored.sort(key=lambda pair: (pair[1], pair[0].id))
    return scored


def _pays_onto(session: Session, tx: Transaction, statement: CreditCardStatement) -> bool:
    """`tx` was paired with a payment arriving on this statement's card (the
    card's export lists the payment) — it may still be this statement's."""
    partner = session.get(Transaction, tx.transfer_pair_id) if tx.transfer_pair_id else None
    return partner is not None and partner.account_id == statement.account_id and partner.amount_minor > 0


def find_exact_match(session: Session, statement: CreditCardStatement) -> Transaction | None:
    """The one bank debit of exactly the statement total in the usual window
    — the payment recommended to the user."""
    exact = [tx for tx, (amount_gap, date_gap) in find_candidate_bank_debits(session, statement)
             if amount_gap == 0 and date_gap <= AUTO_MATCH_MAX_DAY_GAP]
    if len(exact) > 1:
        # a bill is paid after its statement: two equal bills in a row (9.99, 9.99) — the
        # debit after this one's end is its own, the one before it pays the previous bill
        exact = [tx for tx in exact if tx.transaction_date >= statement.statement_period_end]
    return exact[0] if len(exact) == 1 else None


def _known_to_be_a_purchase(session: Session, tx: Transaction) -> bool:
    """A rule or the user sorted this debit as something bought or paid for
    (50.00 at the cash machine, groceries, the rent) — not as a card bill,
    and not left unsorted as an issuer's debit no rule knows is."""
    from app.services.transfer_marking import corrected_fields

    if tx.is_transfer or tx.category in CARD_BILL_CATEGORIES:
        return False
    if tx.category is not None and tx.category not in UNSORTED_CATEGORIES:
        return True
    return (tx.id, "category") in corrected_fields(session, [tx.id])  # left as it is by the user's own choice


def find_automatic_match(session: Session, statement: CreditCardStatement) -> Transaction | None:
    """The payment to link without asking: the exact match — unless it is
    known to be a purchase. The amount alone is not enough for that: linked,
    the debit is a transfer and leaves every total, so a purchase that
    happens to cost what the card's bill is would silently stop counting.
    Such a debit is still suggested, for the user to confirm."""
    tx = find_exact_match(session, statement)
    return tx if tx is not None and not _known_to_be_a_purchase(session, tx) else None


def link_pending_payments(session: Session) -> int:
    """Statements still waiting for their bank debit, matched again — after
    any change that may have freed or claimed a debit (an import, a removal,
    another statement linking one). Statements the user dealt with are left
    alone. Returns how many were linked."""
    statements = session.exec(
        select(CreditCardStatement).where(CreditCardStatement.statement_period_end != None)  # noqa: E711
        .order_by(CreditCardStatement.statement_period_end)
    ).all()
    linked = 0
    for _round in range(3):  # one link may make another one unambiguous
        newly = 0
        # In one query each instead of several per statement: which statements the user dealt
        # with (None: no reconciliation stored yet), which have their payment, and the amounts
        # of the bank debits still free — a statement whose amount is not among them has
        # nothing to be linked with.
        handled_by_statement = dict(session.exec(select(Reconciliation.statement_id, Reconciliation.resolved_by_user)).all())
        paid = set(session.exec(
            select(Transaction.settles_statement_id).where(Transaction.settles_statement_id != None)  # noqa: E711
        ).all())
        free_amounts = set(session.exec(
            select(Transaction.amount_minor).join(Account, Account.id == Transaction.account_id).where(
                Account.account_type != AccountType.CREDIT_CARD, Transaction.amount_minor < 0,
                Transaction.is_duplicate == False, Transaction.settles_statement_id == None,  # noqa: E711, E712
            ).distinct()
        ).all())
        for statement in statements:
            handled = handled_by_statement.get(statement.id)
            if handled or statement.id in paid:
                continue
            # Nothing to link, and its reconciliation is stored already (handled is None: not yet):
            # computing and committing it again after every import made a batch of N files cost N x N.
            if handled is not None and (
                not statement.statement_total_minor or -statement.statement_total_minor not in free_amounts
                or find_automatic_match(session, statement) is None
            ):
                continue
            if reconcile_statement(session, statement.id, auto_match=True).bank_debit_transaction_id is not None:
                newly += 1
        linked += newly
        if not newly:
            break
    return linked


def retire_derived_statements(session: Session, statement: CreditCardStatement) -> int:
    """A real statement arrived for a bill a card export already stood in
    for (a statement derived from it): the derived one goes, its debit is
    free for the real one."""
    removed = 0
    for derived in session.exec(select(CreditCardStatement).where(
        CreditCardStatement.account_id == statement.account_id, CreditCardStatement.id != statement.id,
    )).all():
        info = json.loads(derived.other_totals_json) if derived.other_totals_json else {}
        if not info.get(DERIVED_FROM_EXPORT) or not (derived.statement_period_end and statement.statement_period_end):
            continue
        start = statement.statement_period_start or statement.statement_period_end
        if derived.statement_period_end < start or (derived.statement_period_start or derived.statement_period_end) > statement.statement_period_end:
            continue  # another period
        for payment in session.exec(select(Transaction).where(Transaction.settles_statement_id == derived.id)).all():
            release_payment(session, payment)
            session.add(payment)
        recon = session.exec(select(Reconciliation).where(Reconciliation.statement_id == derived.id)).first()
        if recon is not None:
            session.delete(recon)
        session.flush()
        session.delete(derived)
        removed += 1
    if removed:
        session.commit()
    return removed


EXPLANATION_DUPLICATE = "duplicate_transaction"
EXPLANATION_FEE = "fee"
EXPLANATION_INTEREST = "interest"
EXPLANATION_PARTIAL_PAYMENT = "partial_payment"
EXPLANATION_CURRENCY_CONVERSION = "currency_conversion"
EXPLANATION_PREVIOUS_BALANCE = "previous_balance"


def _explain_tx_vs_statement_diff(statement: CreditCardStatement, diff_minor: int) -> list[str]:
    if diff_minor == 0:
        return []
    other_totals = json.loads(statement.other_totals_json) if statement.other_totals_json else {}
    tags = []
    if other_totals.get("previous_balance") == abs(diff_minor):
        tags.append(EXPLANATION_PREVIOUS_BALANCE)
    if other_totals.get("fee") == abs(diff_minor):
        tags.append(EXPLANATION_FEE)
    if other_totals.get("interest") == abs(diff_minor):
        tags.append(EXPLANATION_INTEREST)
    return tags


def _explain_statement_vs_bank_diff(
    statement: CreditCardStatement, bank_tx: Transaction, diff_minor: int
) -> list[str]:
    if diff_minor == 0:
        return []
    abs_diff = abs(diff_minor)
    tags: list[str] = []

    other_totals = json.loads(statement.other_totals_json) if statement.other_totals_json else {}
    if other_totals.get("fee") == abs_diff:
        tags.append(EXPLANATION_FEE)
    if other_totals.get("interest") == abs_diff:
        tags.append(EXPLANATION_INTEREST)

    if bank_tx.currency != statement.currency:
        tags.append(EXPLANATION_CURRENCY_CONVERSION)

    # Bank debit is smaller than the statement total -> looks like the user
    # only paid part of the bill.
    if abs(bank_tx.amount_minor) < statement.statement_total_minor:
        tags.append(EXPLANATION_PARTIAL_PAYMENT)

    return tags


@dataclass
class ReconciliationFigures:
    transaction_total_minor: int
    statement_total_minor: int | None
    bank_tx: Transaction | None
    diff_transactions_vs_statement_minor: int | None
    diff_statement_vs_bank_minor: int | None
    difference_minor: int | None
    status: ReconciliationStatus
    explanation_tags: list[str] = field(default_factory=list)


def compute_reconciliation(
    session: Session, statement: CreditCardStatement, bank_tx: Transaction | None
) -> ReconciliationFigures:
    """All reconciliation numbers for `statement` given its (possible)
    bank payment. Pure read — never modifies anything."""
    transaction_total = compute_transaction_total_minor(session, statement)

    diff_tx_vs_statement = None
    if statement.statement_total_minor is not None:
        diff_tx_vs_statement = statement.statement_total_minor - transaction_total

    diff_statement_vs_bank = None
    if bank_tx is not None and statement.statement_total_minor is not None:
        diff_statement_vs_bank = abs(bank_tx.amount_minor) - statement.statement_total_minor

    tags: list[str] = []
    if diff_tx_vs_statement:
        tags += _explain_tx_vs_statement_diff(statement, diff_tx_vs_statement)
    if bank_tx is not None and diff_statement_vs_bank:
        tags += _explain_statement_vs_bank_diff(statement, bank_tx, diff_statement_vs_bank)

    if bank_tx is None and statement.statement_total_minor == 0:
        status = ReconciliationStatus.RECONCILED  # nothing owed: no debit to wait for
    elif bank_tx is None:
        status = ReconciliationStatus.PENDING
    elif diff_tx_vs_statement in (None, 0) and diff_statement_vs_bank in (None, 0):
        status = ReconciliationStatus.RECONCILED
    else:
        status = ReconciliationStatus.MISMATCH

    headline = diff_statement_vs_bank if diff_statement_vs_bank is not None else diff_tx_vs_statement

    return ReconciliationFigures(
        transaction_total_minor=transaction_total,
        statement_total_minor=statement.statement_total_minor,
        bank_tx=bank_tx,
        diff_transactions_vs_statement_minor=diff_tx_vs_statement,
        diff_statement_vs_bank_minor=diff_statement_vs_bank,
        difference_minor=headline,
        status=status,
        explanation_tags=sorted(set(tags)),
    )


def current_bank_payment(session: Session, statement: CreditCardStatement) -> Transaction | None:
    return session.exec(select(Transaction).where(Transaction.settles_statement_id == statement.id)).first()


def get_suggested_payments(session: Session, statement: CreditCardStatement) -> list[Transaction]:
    """Candidates to show the user when no payment is linked yet."""
    if current_bank_payment(session, statement) is not None:
        return []
    return [tx for tx, _score in find_candidate_bank_debits(session, statement)]


# Backwards-compatible name.
get_ambiguous_candidates = get_suggested_payments


# ---------------------------------------------------------------------------
# Persisting actions
# ---------------------------------------------------------------------------

def latest_corrected_type(session: Session, tx_id: int) -> TransactionType | None:
    from app.db.models import UserCorrection

    value = session.exec(
        select(UserCorrection.new_value)
        .where(UserCorrection.transaction_id == tx_id, UserCorrection.field == "transaction_type")
        .order_by(UserCorrection.corrected_at.desc(), UserCorrection.id.desc())
    ).first()
    try:
        return TransactionType(value) if value else None
    except ValueError:
        return None


def release_payment(session: Session, tx: Transaction) -> None:
    """Turn a statement's payment back into an ordinary bank transaction —
    unless the user explicitly set its type, which always wins."""
    from app.services.transfer_detection_service import manually_corrected_type_ids, natural_type
    from app.services.transfer_marking import corrected_fields, release_from_transfer

    tx.settles_statement_id = None
    chosen = latest_corrected_type(session, tx.id) if tx.id in manually_corrected_type_ids(session) else None
    if chosen != TransactionType.TRANSFER:
        # back to what the user set, or to what it naturally is
        tx.is_transfer = False
        tx.transaction_type = chosen or natural_type(tx.amount_minor)
        release_from_transfer(session, tx, corrected_fields(session, [tx.id]))
    session.add(tx)


def _claim_payment(session: Session, tx: Transaction, statement: CreditCardStatement) -> None:
    from app.services.transfer_marking import corrected_fields, settle_as_transfer

    if tx.transfer_pair_id is not None:
        # it was paired with the payment arriving on the card; the statement accounts for it now
        partner = session.get(Transaction, tx.transfer_pair_id)
        if partner is not None and partner.transfer_pair_id == tx.id:
            partner.transfer_pair_id = None
            session.add(partner)
    tx.settles_statement_id = statement.id
    tx.is_transfer = True
    tx.transaction_type = TransactionType.TRANSFER
    tx.transfer_pair_id = None
    settle_as_transfer(tx, corrected_fields(session, [tx.id]))


def reconcile_statement(
    session: Session,
    statement_id: int,
    bank_debit_transaction_id: int | None = None,
    auto_match: bool = False,
    clear_bank_payment: bool = False,
) -> Reconciliation:
    """Compute and persist the reconciliation for one statement.

    * `bank_debit_transaction_id` — the user chose this payment.
    * `clear_bank_payment` — the user said the linked payment is wrong.
    * `auto_match` — link a payment automatically if one is unambiguous
      (used after imports); otherwise an existing link is kept as is.
    """
    statement = session.get(CreditCardStatement, statement_id)
    if statement is None:
        raise ReconciliationError(tr("Unknown statement_id={statement_id}", statement_id=statement_id))

    previous = current_bank_payment(session, statement)
    bank_tx: Transaction | None
    if bank_debit_transaction_id is not None:
        bank_tx = session.get(Transaction, bank_debit_transaction_id)
        if bank_tx is None:
            raise ReconciliationError(tr("Unknown bank_debit_transaction_id={bank_debit_transaction_id}", bank_debit_transaction_id=bank_debit_transaction_id))
        account = session.get(Account, bank_tx.account_id)
        if account is None or account.account_type == AccountType.CREDIT_CARD:
            raise ReconciliationError(tr("The payment must be a transaction on a bank account."))
        if bank_tx.amount_minor >= 0:
            raise ReconciliationError(tr("The payment must be money leaving the bank account."))
        if bank_tx.settles_statement_id not in (None, statement.id):
            raise ReconciliationError(tr("This transaction is already the payment of another statement."))
        if bank_tx.transfer_pair_id is not None:
            from app.services.transfer_detection_service import unpair_transfer
            unpair_transfer(session, bank_tx)
    elif clear_bank_payment:
        bank_tx = None
    elif previous is not None:
        bank_tx = previous
    elif auto_match:
        bank_tx = find_automatic_match(session, statement)
    else:
        bank_tx = None

    if previous is not None and (bank_tx is None or previous.id != bank_tx.id):
        release_payment(session, previous)
    if bank_tx is not None:
        _claim_payment(session, bank_tx, statement)
        session.add(bank_tx)
    session.flush()

    figures = compute_reconciliation(session, statement, bank_tx)

    existing = session.exec(select(Reconciliation).where(Reconciliation.statement_id == statement_id)).first()
    if existing is None:
        existing = Reconciliation(statement_id=statement_id, transaction_total_minor=figures.transaction_total_minor)
    existing.transaction_total_minor = figures.transaction_total_minor
    existing.statement_total_minor = figures.statement_total_minor
    existing.bank_debit_transaction_id = bank_tx.id if bank_tx else None
    existing.bank_debit_amount_minor = bank_tx.amount_minor if bank_tx else None
    existing.diff_transactions_vs_statement_minor = figures.diff_transactions_vs_statement_minor
    existing.diff_statement_vs_bank_minor = figures.diff_statement_vs_bank_minor
    existing.difference_minor = figures.difference_minor
    existing.status = figures.status
    existing.explanation_tags_json = json.dumps(figures.explanation_tags) if figures.explanation_tags else None
    existing.updated_at = utcnow()

    session.add(existing)
    session.commit()
    session.refresh(existing)
    return existing


EXPORT_BILL_MAX_DAY_GAP = 40
DERIVED_FROM_EXPORT = "derived_from_export"


def derive_statements_from_exports(session: Session) -> int:
    """A card's export (a list of bookings, no statement) whose purchases add
    up exactly to a later bank debit for a card bill IS that bill's statement
    — e.g. one billing period exported as CSV. Without this, the purchases
    and the bill would both count as expenses. The statement is created
    (marked as derived) and reconciled; returns how many were created."""
    from app.db.models import DocumentType, ImportRecord, ImportStatus

    card_ids = set(session.exec(select(Account.id).where(Account.account_type == AccountType.CREDIT_CARD)).all())
    if not card_ids:
        return 0
    has_statement = set(session.exec(select(CreditCardStatement.import_id)).all())
    bank_ids = set(session.exec(select(Account.id).where(Account.account_type != AccountType.CREDIT_CARD)).all())
    claimed = _claimed_payment_ids(session)
    created = 0
    for record in session.exec(select(ImportRecord).where(
        ImportRecord.account_id.in_(card_ids), ImportRecord.status == ImportStatus.IMPORTED,
        ImportRecord.document_type != DocumentType.CREDIT_CARD_STATEMENT,
    )).all():
        if record.id in has_statement or not record.period_end:
            continue
        rows = session.exec(
            select(Transaction).join(RawTransaction, RawTransaction.id == Transaction.raw_transaction_id).where(
                RawTransaction.import_id == record.id, Transaction.is_duplicate == False,  # noqa: E712
                Transaction.is_transfer == False,  # noqa: E712
            )
        ).all()
        net = -sum(t.amount_minor for t in rows)
        if len(rows) < 2 or net <= 0:
            continue
        bills = [
            tx for tx in session.exec(select(Transaction).where(
                Transaction.account_id.in_(bank_ids), Transaction.amount_minor == -net,
                Transaction.transaction_date >= record.period_end,
                Transaction.transaction_date <= record.period_end + timedelta(days=EXPORT_BILL_MAX_DAY_GAP),
                Transaction.is_transfer == False, Transaction.is_duplicate == False,  # noqa: E712
            )).all()
            if tx.id not in claimed and tx.category in CARD_BILL_CATEGORIES
        ]
        if len(bills) != 1:
            continue
        account = session.get(Account, record.account_id)
        statement = CreditCardStatement(
            account_id=record.account_id, import_id=record.id,
            statement_period_start=record.period_start, statement_period_end=record.period_end,
            statement_total_minor=net, currency=account.currency if account else "EUR",
            other_totals_json=json.dumps({DERIVED_FROM_EXPORT: 1}),
        )
        session.add(statement)
        session.commit()
        reconcile_statement(session, statement.id, bank_debit_transaction_id=bills[0].id)
        claimed.add(bills[0].id)
        created += 1
    return created


def resolve_reconciliation(
    session: Session,
    reconciliation_id: int,
    notes: str | None = None,
    tags: list[str] | None = None,
) -> Reconciliation:
    """Manual resolution/annotation — never auto-deletes or silently
    overwrites the computed numbers, only records the user's judgement on
    top of them. User-provided tags are stored separately from the
    engine's own computed explanation_tags_json."""
    reconciliation = session.get(Reconciliation, reconciliation_id)
    if reconciliation is None:
        raise ReconciliationError(tr("Unknown reconciliation_id={reconciliation_id}", reconciliation_id=reconciliation_id))

    reconciliation.resolved_by_user = True
    if notes is not None:
        reconciliation.resolution_notes = notes
    if tags is not None:
        reconciliation.user_resolution_tags_json = json.dumps(sorted(set(tags)))

    session.add(reconciliation)
    session.commit()
    session.refresh(reconciliation)
    return reconciliation
