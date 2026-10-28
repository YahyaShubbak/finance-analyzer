"""Shared query-parameter parsing."""
from __future__ import annotations

from fastapi import HTTPException

from app.i18n import tr


def parse_account_ids(account_id: str | None) -> list[int] | None:
    """Comma-separated account ids ("1,3") -> [1, 3]; 422 on garbage
    instead of an unhandled 500."""
    if not account_id:
        return None
    try:
        return [int(x) for x in account_id.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=422, detail=tr("account_id must be a comma-separated list of numbers.")) from None
