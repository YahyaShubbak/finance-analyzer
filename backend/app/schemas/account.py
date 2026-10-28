from __future__ import annotations

import re
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import AccountType
from app.i18n import tr
from app.importers.currency import is_valid_currency
from app.importers.parsing_utils import MAX_AMOUNT_MINOR


def normalize_iban(value: str | None) -> str | None:
    """Uppercase without spaces, validated with the ISO 13616 mod-97 check
    so a typo can't silently break transfer detection."""
    if value is None:
        return None
    iban = re.sub(r"\s+", "", value).upper()
    if not iban:
        return None
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
        raise ValueError(tr("not a valid IBAN"))
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    if int(digits) % 97 != 1:
        raise ValueError(tr("IBAN check digits are wrong — please check for typos"))
    return iban


def _validate_currency(value: str | None) -> str | None:
    if value is None:
        return None
    code = value.strip().upper()
    if not is_valid_currency(code):
        raise ValueError(tr("must be a 3-letter ISO 4217 currency code, e.g. EUR"))
    return code


MAX_NAME_LENGTH = 100


def _clean_name(value: str) -> str:
    """An account's name: one line of text, not empty, not endless."""
    value = " ".join("".join(ch if ch.isprintable() else " " for ch in value).split())
    if not value:
        raise ValueError(tr("must not be empty"))
    if len(value) > MAX_NAME_LENGTH:
        raise ValueError(tr("must be at most {count} characters", count=MAX_NAME_LENGTH))
    return value


class AccountCreate(BaseModel):
    name: str
    account_type: AccountType
    currency: str = "EUR"
    iban: str | None = None

    @field_validator("currency")
    @classmethod
    def _currency(cls, v: str) -> str:
        return _validate_currency(v)

    @field_validator("iban")
    @classmethod
    def _iban(cls, v: str | None) -> str | None:
        return normalize_iban(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _clean_name(v)


class AccountUpdate(BaseModel):
    name: str | None = None
    currency: str | None = None
    is_archived: bool | None = None
    # These support explicit clearing (set to null) as well as setting —
    # see the route for how that's distinguished from "not provided at all".
    iban: str | None = None
    opening_balance_minor: int | None = Field(default=None, ge=-MAX_AMOUNT_MINOR, le=MAX_AMOUNT_MINOR)
    opening_balance_date: date | None = None

    @field_validator("currency")
    @classmethod
    def _currency(cls, v: str | None) -> str | None:
        return _validate_currency(v)

    @field_validator("iban")
    @classmethod
    def _iban(cls, v: str | None) -> str | None:
        return normalize_iban(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return None if v is None else _clean_name(v)


class AccountRead(BaseModel):
    id: int
    name: str
    account_type: AccountType
    currency: str
    iban: str | None = None
    created_at: datetime
    is_archived: bool
    transaction_count: int = 0

    # The three distinct balance figures (never conflated).
    transactions_balance_minor: int = 0
    opening_balance_minor: int | None = None
    opening_balance_date: date | None = None
    current_balance_minor: int = 0

    model_config = ConfigDict(from_attributes=True)
