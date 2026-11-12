"""On start-up (and after a restored backup): card bills that an older
version left as ordinary expenses are linked to their card.

(Above the reconciliation and the transfer detection, which it runs one
after the other.)
"""
from __future__ import annotations

import logging

from sqlmodel import Session

from app.reconciliation.engine import derive_statements_from_exports, link_pending_payments
from app.services.transfer_detection_service import detect_and_mark_transfers
from app.services.transfer_marking import retype_card_payments, sort_card_bill_payees

logger = logging.getLogger("finance")


def link_card_bills(session: Session) -> None:
    """On start-up: link card bills that older versions left as expenses —
    a statement's payment line paying the previous bill, a card export that
    is one billing period. A failure here must never keep the app from starting."""
    try:
        retype_card_payments(session)
        derive_statements_from_exports(session)
        link_pending_payments(session)
        detect_and_mark_transfers(session)
        sort_card_bill_payees(session)
    except Exception:  # noqa: BLE001 — logged; the bills just stay unlinked
        session.rollback()
        logger.exception("Could not link card bills")
