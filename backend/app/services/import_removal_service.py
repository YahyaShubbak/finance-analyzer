"""Removes an entire import and everything derived from it (spec
Milestone 3, section 6), without leaving dangling references or silently
corrupting unrelated data:

* Only transactions/raw rows belonging to THIS import are removed.
* If a removed transaction was one half of an auto-detected transfer
  pair, its partner is reverted to its natural (non-transfer) state
  rather than being left pointing at a transaction that no longer exists.
* If this import IS a credit-card statement's source, the statement and
  its reconciliation are removed with it (they have no meaning without
  their underlying data).
* If a removed transaction was some OTHER statement's matched bank
  payment, that reconciliation is not left stale — its bank-payment link
  is cleared and the reconciliation is recomputed from scratch (which may
  find a different candidate, flag ambiguity, or fall back to pending).
* Any duplicate_of_id pointing at a removed transaction is cleared.
* UserCorrection audit rows for removed transactions are removed with
  them (an audit trail for a transaction that no longer exists is
  meaningless).

Runs as explicit staged deletes/updates with flushes between stages,
since the app enables SQLite's foreign-key enforcement (PRAGMA
foreign_keys=ON) — an update that clears a reference must be flushed
before the row it used to point to is deleted, or the delete fails.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlmodel import Session, delete, select

from app.db.chunks import chunked
from app.db.models import (
    CreditCardStatement,
    ImportRecord,
    RawTransaction,
    Reconciliation,
    Transaction,
    UserCorrection,
)
from app.i18n import tr
from app.reconciliation.engine import reconcile_statement, release_payment
from app.services.import_staging import stored_import_path
from app.services.transfer_detection_service import unpair_transfer


class ImportRemovalError(Exception):
    pass


@dataclass
class ImportRemovalResult:
    import_id: int
    filename: str
    transactions_removed: int
    raw_transactions_removed: int
    transfer_partners_reverted: int
    statements_removed: int
    reconciliations_recomputed: int


def _rehome_shared_bookings(session: Session, import_id: int, removed: dict[int, Transaction]) -> set[int]:
    """Moves bookings of the removed file that other files also contain to
    one of those files' rows. Returns the ids of the bookings kept."""
    if not removed:
        return set()
    others: dict[int, list[RawTransaction]] = {}
    for raw in session.exec(
        select(RawTransaction).where(
            RawTransaction.import_id != import_id, RawTransaction.extra_fields_json.like('%"_duplicate_of"%')
        ).order_by(RawTransaction.import_id, RawTransaction.id)
    ).all():
        try:
            target = json.loads(raw.extra_fields_json).get("_duplicate_of")
        except (ValueError, AttributeError):
            continue
        if target in removed:
            others.setdefault(target, []).append(raw)
    for tx_id, raws in others.items():
        tx, row = removed[tx_id], raws[0]
        extra = json.loads(row.extra_fields_json)
        extra.pop("_duplicate_of", None)
        row.extra_fields_json = json.dumps(extra, ensure_ascii=False) if extra else None
        tx.raw_transaction_id = row.id
        tx.normalized_description = (row.original_description or tx.normalized_description).strip()
        session.add(row)
        session.add(tx)
    session.flush()
    return set(others)


def remove_import(session: Session, import_id: int) -> ImportRemovalResult:
    import_record = session.get(ImportRecord, import_id)
    if import_record is None:
        raise ImportRemovalError(tr("Unknown import_id={import_id}", import_id=import_id))

    period = (import_record.period_start, import_record.period_end)
    filename = import_record.filename
    raw_transactions = session.exec(
        select(RawTransaction).where(RawTransaction.import_id == import_id)
    ).all()
    raw_ids = [r.id for r in raw_transactions]

    tx_to_remove = [
        t for chunk in chunked(raw_ids)
        for t in session.exec(select(Transaction).where(Transaction.raw_transaction_id.in_(chunk))).all()
    ]
    # 0. A booking that another, still imported file contains too (its row
    # was skipped there as an exact duplicate) stays: it now belongs to that
    # file's row, with everything learned or corrected about it.
    kept = _rehome_shared_bookings(session, import_id, {t.id: t for t in tx_to_remove})
    tx_to_remove = [t for t in tx_to_remove if t.id not in kept]
    tx_ids_to_remove = {t.id for t in tx_to_remove}
    # bookings of other files this file's skipped rows stood for (they may have told its place)
    merged_into = set()
    for r in raw_transactions:
        try:
            target = json.loads(r.extra_fields_json).get("_duplicate_of") if r.extra_fields_json else None
        except (ValueError, AttributeError):
            target = None
        if isinstance(target, int) and target not in tx_ids_to_remove:
            merged_into.add(target)

    # 1. Revert any transfer partner whose OTHER half is being removed —
    # never leave a transfer_pair_id pointing at a soon-to-be-deleted row.
    transfer_partners_reverted = 0
    for t in tx_to_remove:
        if t.transfer_pair_id and t.transfer_pair_id not in tx_ids_to_remove:
            if session.get(Transaction, t.transfer_pair_id) is not None:
                # (a payment onto a card stays a transfer; others are sorted by the rules again)
                unpair_transfer(session, t)
                transfer_partners_reverted += 1
    session.flush()

    # 2. Clear (not yet delete) any reconciliation whose matched bank
    # payment is about to be removed, so step 6 doesn't hit a live FK
    # reference. Recomputed fresh after the deletes actually happen.
    affected_reconciliation_statement_ids: list[int] = []
    if tx_ids_to_remove:
        recs_referencing = [
            r for chunk in chunked(list(tx_ids_to_remove))
            for r in session.exec(select(Reconciliation).where(Reconciliation.bank_debit_transaction_id.in_(chunk))).all()
        ]
        for rec in recs_referencing:
            rec.bank_debit_transaction_id = None
            rec.bank_debit_amount_minor = None
            session.add(rec)
            affected_reconciliation_statement_ids.append(rec.statement_id)
    session.flush()

    # 3. If this import itself created credit-card statement(s), remove
    # those and their reconciliations — they have no meaning without the
    # transactions/import they were built from. The bank payment that was
    # linked to such a statement becomes an ordinary expense again
    # (otherwise it would stay excluded from all totals forever).
    statements_from_this_import = session.exec(
        select(CreditCardStatement).where(CreditCardStatement.import_id == import_id)
    ).all()
    for stmt in statements_from_this_import:
        for payment in session.exec(select(Transaction).where(Transaction.settles_statement_id == stmt.id)).all():
            if payment.id in tx_ids_to_remove:
                payment.settles_statement_id = None
                session.add(payment)
            else:
                release_payment(session, payment)
        recon = session.exec(select(Reconciliation).where(Reconciliation.statement_id == stmt.id)).first()
        if recon is not None:
            session.delete(recon)
        # Don't bother recomputing a reconciliation we're about to delete.
        if stmt.id in affected_reconciliation_statement_ids:
            affected_reconciliation_statement_ids.remove(stmt.id)
    session.flush()
    for stmt in statements_from_this_import:
        session.delete(stmt)
    session.flush()

    # 4. Clear duplicate_of_id references from transactions NOT being
    # removed that pointed at one that is: with its twin gone, such a
    # booking (e.g. the same purchase from the card's export) counts again.
    if tx_ids_to_remove:
        dependents = [
            d for chunk in chunked(list(tx_ids_to_remove))
            for d in session.exec(select(Transaction).where(Transaction.duplicate_of_id.in_(chunk))).all()
        ]
        for d in dependents:
            if d.id not in tx_ids_to_remove:
                d.duplicate_of_id = None
                d.is_duplicate = False
                session.add(d)
    session.flush()

    # 5. Delete audit records for the transactions being removed — an
    # audit trail for a transaction that no longer exists is meaningless.
    if tx_ids_to_remove:
        for chunk in chunked(list(tx_ids_to_remove)):
            session.exec(delete(UserCorrection).where(UserCorrection.transaction_id.in_(chunk)))
    session.flush()

    # 5b. Points: this file's go with it; other files' points keep their
    # number but lose the booking that is being removed.
    from app.services.points_service import forget_points

    forget_points(session, import_id, tx_ids_to_remove)
    session.flush()

    # 6. Delete the transactions themselves.
    for t in tx_to_remove:
        session.delete(t)
    session.flush()

    # 7. Delete the raw transactions.
    for r in raw_transactions:
        session.delete(r)
    session.flush()

    # 8. Delete the import record itself.
    stored_file = stored_import_path(import_record.stored_path)
    session.delete(import_record)
    session.commit()
    if merged_into:
        from app.services.location_service import refresh_locations
        refresh_locations(session, merged_into)

    # The original document is gone from the database, so it must not
    # linger on disk either (it is a full bank statement).
    if stored_file is not None:
        try:
            stored_file.unlink(missing_ok=True)
        except OSError:
            pass  # e.g. opened in another program on Windows; harmless

    # 9. Recompute any reconciliation whose bank payment we cleared —
    # never leave it silently stale; it may find a different candidate,
    # come back ambiguous, or fall back to pending.
    reconciliations_recomputed = 0
    for statement_id in affected_reconciliation_statement_ids:
        if session.get(CreditCardStatement, statement_id) is not None:
            reconcile_statement(session, statement_id)
            reconciliations_recomputed += 1

    # 10. A payment released above (its other half was in this file) may
    # settle another statement or pair with another booking instead.
    if (transfer_partners_reverted or statements_from_this_import) and period[0] and period[1]:
        from datetime import timedelta

        from app.normalization.transfers import IBAN_MATCH_MAX_DAY_GAP
        from app.reconciliation.engine import SUGGESTION_MAX_DAY_GAP, link_pending_payments
        from app.services.transfer_detection_service import detect_and_mark_transfers

        # any statement may take a freed debit — also one weeks after this file's dates
        link_pending_payments(session)
        gap = timedelta(days=max(IBAN_MATCH_MAX_DAY_GAP, SUGGESTION_MAX_DAY_GAP))
        detect_and_mark_transfers(session, date_window=(period[0] - gap, period[1] + gap))

    return ImportRemovalResult(
        import_id=import_id,
        filename=filename,
        transactions_removed=len(tx_to_remove),
        raw_transactions_removed=len(raw_transactions),
        transfer_partners_reverted=transfer_partners_reverted,
        statements_removed=len(statements_from_this_import),
        reconciliations_recomputed=reconciliations_recomputed,
    )
