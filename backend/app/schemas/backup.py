from __future__ import annotations

from pydantic import BaseModel


class BackupInfoRead(BaseModel):
    filename: str
    created_at: str
    size_bytes: int
    counts: dict[str, int]


class RestoreResultRead(BaseModel):
    restored_from: str
    safety_backup: str
    counts: dict[str, int]
