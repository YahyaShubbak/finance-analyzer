"""Bookings counted twice because they came from both kinds of file of an
account — a card's PDF statements and its spreadsheet export, imported in
either order before such twins were recognized (see
duplicate_preview_service: CROSS_FILE_DATE_WINDOW_DAYS). Once per
TWINS_VERSION, on start-up, each pair becomes one booking: the other one is
marked a duplicate (kept for traceability, left out of all totals).

The one kept is the one the user corrected or that is linked (a transfer,
a card bill's payment); else the one imported first.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from sqlmodel import Session, select

from app.db.models import CreditCardStatement, ImportRecord, PointsEntry, RawTransaction, Transaction
from app.normalization.category import UNSORTED_CATEGORIES

logger = logging.getLogger("finance")

#: raise when twins are recognized differently
TWINS_VERSION = "1"
#: in the data folder: the TWINS_VERSION the bookings were last checked with
TWINS_MARKER = ".twins_version"


def _linked(tx: Transaction) -> bool:
    return bool(tx.is_transfer or tx.transfer_pair_id or tx.settles_statement_id)


def _source(record: ImportRecord):
    from app.services.duplicate_preview_service import SourceFile, file_kind

    return SourceFile(file_kind(record.filename), record.period_start, record.period_end)


def find_twins(session: Session) -> list[tuple[Transaction, Transaction]]:
    """(kept, duplicate) pairs."""
    from app.services.duplicate_preview_service import (
        CROSS_FILE_DATE_WINDOW_DAYS,
        _descriptions_overlap,
        _same_merchant,
        file_kind,
        twin_dates_fit,
    )
    from app.services.import_service import KEPT_BY_USER
    from app.services.transfer_marking import corrected_fields

    rows = [
        (tx, record) for tx, record, raw in session.exec(
            select(Transaction, ImportRecord, RawTransaction)
            .join(RawTransaction, RawTransaction.id == Transaction.raw_transaction_id)
            .join(ImportRecord, ImportRecord.id == RawTransaction.import_id)
            .where(Transaction.is_duplicate == False)  # noqa: E712
        ).all()
        if KEPT_BY_USER not in (raw.extra_fields_json or "")  # the user said: a booking of its own
    ]
    corrected = {tx_id for tx_id, _field in corrected_fields(session)}
    groups: dict[tuple[int, int], dict[str, list]] = defaultdict(lambda: {"pdf": [], "export": []})
    for tx, record in rows:
        groups[(tx.account_id, tx.amount_minor)][file_kind(record.filename)].append((tx, record))

    pairs = []
    for group in groups.values():
        exports = sorted(group["export"], key=lambda r: r[0].transaction_date)
        used: set[int] = set()
        for tx, record in sorted(group["pdf"], key=lambda r: r[0].transaction_date):
            candidates = [
                (abs((other.transaction_date - tx.transaction_date).days), other, other_record)
                for other, other_record in exports
                if other.id not in used and abs((other.transaction_date - tx.transaction_date).days) <= CROSS_FILE_DATE_WINDOW_DAYS
                and twin_dates_fit(tx.transaction_date, _source(record), other.transaction_date, _source(other_record))
                and (_same_merchant(tx.merchant, other.merchant)
                     or _descriptions_overlap(tx.normalized_description, other.normalized_description))
            ]
            if not candidates:
                continue
            _gap, other, other_record = min(candidates, key=lambda c: (c[0], c[1].id))
            used.add(other.id)

            def rank(item):
                t, r = item
                return (t.id in corrected, _linked(t), -r.id)

            kept, dropped = sorted([(tx, record), (other, other_record)], key=rank, reverse=True)
            if _linked(dropped[0]):
                continue  # both linked: left to the user
            pairs.append((kept[0], dropped[0]))
    return pairs


def merge_cross_file_twins(session: Session, force: bool = False) -> int:
    """Returns how many bookings were counted twice. Never keeps the app from starting."""
    from app.config import settings
    from app.reconciliation.engine import reconcile_statement

    marker = settings.data_dir / TWINS_MARKER
    try:
        if not force and marker.exists() and marker.read_text(encoding="utf-8").strip() == TWINS_VERSION:
            return 0
        pairs = find_twins(session)
        accounts = set()
        for kept, dropped in pairs:
            if (kept.category in UNSORTED_CATEGORIES and dropped.category not in UNSORTED_CATEGORIES
                    and not dropped.is_transfer):
                kept.category = dropped.category  # e.g. the export's merchant category sorted it
                kept.needs_review = dropped.needs_review
            dropped.is_duplicate, dropped.duplicate_of_id = True, kept.id
            dropped.needs_review, dropped.review_reason = False, None
            for entry in session.exec(select(PointsEntry).where(PointsEntry.transaction_id == dropped.id)).all():
                entry.transaction_id = kept.id
                session.add(entry)
            session.add(kept)
            session.add(dropped)
            accounts.add(kept.account_id)
        session.commit()
        for statement in session.exec(select(CreditCardStatement)).all():
            if statement.account_id in accounts:
                reconcile_statement(session, statement.id)  # its bookings' total changed
        marker.write_text(TWINS_VERSION, encoding="utf-8")
        if pairs:
            logger.info("Merged %d bookings counted twice (statement and export)", len(pairs))
        return len(pairs)
    except Exception:  # noqa: BLE001
        session.rollback()
        logger.exception("Could not merge bookings counted twice")
        return 0
