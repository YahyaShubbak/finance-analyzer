from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.transfers import TransferDetectionResponse
from app.services.transfer_detection_service import run_transfer_detection

router = APIRouter(prefix="/api/transfers", tags=["transfers"])


@router.post("/rerun-detection", response_model=TransferDetectionResponse)
def rerun_detection(session: Session = Depends(get_session)):
    """Explicitly re-evaluates transfer detection across all eligible
    transactions (spec: keep classification safe against import order).
    Never touches manually-corrected transactions or credit-card
    reconciliation's own transfer matches.
    """
    result = run_transfer_detection(session, full_rescan=True)
    return TransferDetectionResponse(
        transactions_considered=result.transactions_considered,
        pairs_matched=result.pairs_matched,
        transactions_marked_as_transfer=result.transactions_marked_as_transfer,
        transactions_reverted_to_ordinary=result.transactions_reverted_to_ordinary,
    )
