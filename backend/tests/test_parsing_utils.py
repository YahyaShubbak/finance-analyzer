from decimal import Decimal

import pytest

from app.importers.parsing_utils import (
    AmountParseError,
    DateParseError,
    parse_amount_to_decimal,
    parse_amount_to_minor_units,
    parse_date_flexible,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("42,90", Decimal("42.90")),
        ("42.90", Decimal("42.90")),
        ("-42,90", Decimal("-42.90")),
        ("1.234,56", Decimal("1234.56")),   # German thousands+decimal comma
        ("1,234.56", Decimal("1234.56")),   # US thousands+decimal point
        ("(42,90)", Decimal("-42.90")),     # accounting negative notation
        ("+100,00", Decimal("100.00")),
        ("€ 45,67", Decimal("45.67")),
        ("45.67 EUR", Decimal("45.67")),
    ],
)
def test_parse_amount_to_decimal(raw, expected):
    assert parse_amount_to_decimal(raw) == expected


def test_parse_amount_rejects_empty():
    with pytest.raises(AmountParseError):
        parse_amount_to_decimal("")


def test_parse_amount_to_minor_units():
    assert parse_amount_to_minor_units("42,90") == 4290
    assert parse_amount_to_minor_units("-129,99") == -12999


def test_sub_cent_precision_is_rejected_not_rounded():
    # A third decimal in a bank export almost always means the separator
    # was misread — rounding it away would hide a factor-1000 error.
    with pytest.raises(AmountParseError):
        parse_amount_to_minor_units("42.905", ".")


@pytest.mark.parametrize(
    "raw,iso",
    [
        ("2026-01-15", "2026-01-15"),
        ("15.01.2026", "2026-01-15"),
        ("01/15/2026", "2026-01-15"),
        ("15-01-2026", "2026-01-15"),
    ],
)
def test_parse_date_flexible(raw, iso):
    assert parse_date_flexible(raw).isoformat() == iso


def test_parse_date_rejects_garbage():
    with pytest.raises(DateParseError):
        parse_date_flexible("not-a-date")
