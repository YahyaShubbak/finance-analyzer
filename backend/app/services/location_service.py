"""Keeps Transaction.country / city / online in step with
app.normalization.location: worked out on import, and again for every
transaction whose location_version is behind (on start-up)."""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from app.db.chunks import chunked
from app.db.models import Account, AccountType, RawTransaction, Transaction, TransactionType
from app.normalization.location import LOCATION_VERSION, LocationInput, locate_rows

logger = logging.getLogger("finance")


def _extra(raw: RawTransaction) -> dict:
    try:
        value = json.loads(raw.extra_fields_json) if raw.extra_fields_json else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def refresh_locations(session: Session, transaction_ids: Iterable[int] | None = None) -> int:
    """Work out the location of the given transactions — or, without ids,
    of every transaction whose location is outdated. The whole file each
    of them came from is looked at (see locate_rows). Commits; returns how
    many transactions changed."""
    imports = select(RawTransaction.import_id).join(Transaction, Transaction.raw_transaction_id == RawTransaction.id)
    if transaction_ids is None:
        import_ids = set(session.exec(imports.where(Transaction.location_version != LOCATION_VERSION).distinct()).all())
    else:
        import_ids = {
            i for chunk in chunked(set(transaction_ids))
            for i in session.exec(imports.where(Transaction.id.in_(chunk)).distinct()).all()
        }
    if not import_ids:
        return 0
    rows = session.exec(
        select(Transaction, RawTransaction)
        .join(RawTransaction, Transaction.raw_transaction_id == RawTransaction.id)
        .where(RawTransaction.import_id.in_(import_ids))
    ).all()
    accounts = {a.id: a for a in session.exec(select(Account)).all()}

    # Rows of other files that were recognized as these same bookings and
    # skipped on import (duplicate_of_transaction_id) still tell their place,
    # e.g. the merchant's town column of a card export matching a PDF statement.
    skipped = aliased(RawTransaction)
    located = (
        select(Transaction.id)
        .join(RawTransaction, Transaction.raw_transaction_id == RawTransaction.id)
        .where(RawTransaction.import_id.in_(import_ids))
    )
    merged: dict[int, list[dict]] = defaultdict(list)
    for raw in session.exec(
        select(skipped).where(skipped.duplicate_of_transaction_id.in_(located)).order_by(skipped.id)
    ).all():
        merged[raw.duplicate_of_transaction_id].append(_extra(raw))

    by_import: dict[int, list[tuple[Transaction, RawTransaction]]] = defaultdict(list)
    for tx, raw in rows:
        by_import[raw.import_id].append((tx, raw))

    changed = 0
    for pairs in by_import.values():
        inputs = []
        for tx, raw in pairs:
            account = accounts.get(tx.account_id)
            extra = _extra(raw)
            on_card = account is not None and account.account_type == AccountType.CREDIT_CARD
            purchase = not tx.is_transfer and tx.transaction_type != TransactionType.TRANSFER
            inputs.append(LocationInput(
                texts=[raw.original_description, extra.get("_details")],
                extra_fields=[extra, *merged.get(tx.id, [])],
                card_text=raw.original_description if on_card and purchase else None,
                currency=tx.currency,
                account_currency=account.currency if account else None,
            ))
        for (tx, _raw), location in zip(pairs, locate_rows(inputs), strict=True):
            new = (location.country, location.city, location.online, LOCATION_VERSION)
            if (tx.country, tx.city, tx.online, tx.location_version) != new:
                if (tx.country, tx.city, tx.online) != new[:3]:
                    changed += 1
                tx.country, tx.city, tx.online, tx.location_version = new
                session.add(tx)
    session.commit()
    return changed


def refresh_outdated_locations(session: Session) -> None:
    """On start-up. A failure here must never keep the app from starting."""
    try:
        changed = refresh_locations(session)
        if changed:
            logger.info("Worked out the location of %d transactions", changed)
    except Exception:  # noqa: BLE001 — logged, the app works without locations
        session.rollback()
        logger.exception("Could not work out transaction locations")
