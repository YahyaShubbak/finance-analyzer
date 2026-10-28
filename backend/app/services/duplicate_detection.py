"""Transaction-level duplicate detection (spec section 11).

Two layers:
1. File-level: identical file re-uploaded -> detected via sha256 checksum
   on ImportRecord (handled in import_service).
2. Transaction-level: the same real-world transaction appearing via two
   different files (or twice in one file) -> detected via a composite
   fingerprint of (account, date, amount, normalized description).

Nothing is ever auto-deleted. Duplicates are flagged (is_duplicate=True,
duplicate_of_id set) and excluded from analytics totals, but remain in
the database for audit purposes.
"""
from __future__ import annotations

import hashlib
import re


def _normalize_description_for_fingerprint(description: str | None) -> str:
    if not description:
        return ""
    text = description.strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\d{4,}", "", text)  # strip long reference numbers that vary between exports
    return text.strip()


def compute_duplicate_fingerprint(
    account_id: int,
    transaction_date_iso: str,
    amount_minor: int,
    description: str | None,
) -> str:
    normalized_desc = _normalize_description_for_fingerprint(description)
    payload = f"{account_id}|{transaction_date_iso}|{amount_minor}|{normalized_desc}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
