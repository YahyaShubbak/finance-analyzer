"""Card statements imported with an older reader get the totals the reader
finds now — once per STATEMENTS_VERSION, on start-up. E.g. Bank Norwegian's
"Rechnungsbetrag der Vorperiode" was taken for the statement's amount, so
its bank debit was looked for with the previous bill's amount.

Only the statement's figures change (its bookings are the user's data and
stay); its payment is matched again — unless the user chose it.
"""
from __future__ import annotations

import json
import logging

from sqlmodel import Session, select

from app.db.models import CreditCardStatement, DocumentType, ImportRecord, Reconciliation
from app.importers.base import ParseOptions

logger = logging.getLogger("finance")

#: raise when the card readers find statement totals differently, or payments are linked differently
STATEMENTS_VERSION = "2"
#: in the data folder: the STATEMENTS_VERSION the stored statements were last read with
STATEMENTS_MARKER = ".statements_version"


def refresh_statement_totals(session: Session, force: bool = False) -> int:
    """Returns how many statements were corrected. Never keeps the app from starting."""
    from app.config import settings
    from app.reconciliation.engine import current_bank_payment, reconcile_statement, release_payment
    from app.services.import_service import parse_file
    from app.services.import_staging import stored_import_path

    marker = settings.data_dir / STATEMENTS_MARKER
    try:
        if not force and marker.exists() and marker.read_text(encoding="utf-8").strip() == STATEMENTS_VERSION:
            return 0
        corrected = 0
        for statement in session.exec(select(CreditCardStatement)).all():
            record = session.get(ImportRecord, statement.import_id)
            path = stored_import_path(record.stored_path) if record and record.filename.lower().endswith(".pdf") else None
            if path is None or not path.exists():
                continue
            try:
                info = json.loads(record.source_info_json) if record.source_info_json else {}
                parsed = parse_file(path, original_filename=record.filename,
                                    options=ParseOptions.from_dict(info.get("options")) if info.get("options") else None)
            except Exception:  # noqa: BLE001 — that statement keeps its figures
                logger.debug("Could not read %s again", record.filename, exc_info=True)
                continue
            other = json.dumps(parsed.other_totals) if parsed.other_totals else None
            if parsed.document_type != DocumentType.CREDIT_CARD_STATEMENT or \
                    (parsed.statement_total_minor, other) == (statement.statement_total_minor, statement.other_totals_json):
                continue
            statement.statement_total_minor, statement.other_totals_json = parsed.statement_total_minor, other
            session.add(statement)
            payment = current_bank_payment(session, statement)
            chosen = session.exec(select(Reconciliation.resolved_by_user).where(
                Reconciliation.statement_id == statement.id)).first()
            if payment is not None and not chosen and abs(payment.amount_minor) != (statement.statement_total_minor or 0):
                release_payment(session, payment)  # linked for the old amount
            session.flush()
            reconcile_statement(session, statement.id, auto_match=True)
            corrected += 1
        session.commit()
        from app.reconciliation.engine import link_pending_payments

        linked = link_pending_payments(session)
        marker.write_text(STATEMENTS_VERSION, encoding="utf-8")
        if corrected or linked:
            logger.info("Corrected the totals of %d card statements, linked %d payments", corrected, linked)
        return corrected
    except Exception:  # noqa: BLE001
        session.rollback()
        logger.exception("Could not read the card statements again")
        return 0

