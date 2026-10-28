from __future__ import annotations

from pydantic import BaseModel


class TransferDetectionResponse(BaseModel):
    transactions_considered: int
    pairs_matched: int
    transactions_marked_as_transfer: int
    transactions_reverted_to_ordinary: int
