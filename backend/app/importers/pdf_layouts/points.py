"""Bonus points (and miles) printed on card statements.

Statements show them in a few shapes, all read here from the text lines:

* under a booking, what it earned: "+40 SHOP PUNKTE", "+20 SHOP PRIME
  PUNKTE" (negative for a refund) — the line belongs to the booking above
  it, also when a page break comes between them;
* a table of redemptions: "EINGELOESTE SHOP PUNKTE 10.03.2026 500 - 5,00 -";
* the balance: under "alter Stand … neu gesammelt … eingelöst … neuer Stand"
  a line "Shop Punkte + 1.000 - 200 - 500 + 300";
* the conversion: "100 Shop Punkte entsprechen 1 Euro";
* a partner program's monthly sum: "Neu gesammelte PARTNER Punkte über
  <card> 250" with "Zeitraum vom 01.03.26 bis 31.03.26".

Nothing here is a booking: points don't change any balance in euros.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.importers.parsing_utils import DateParseError, parse_date_flexible
from app.importers.pdf_layouts.patterns import complete_date

_UNITS = r"PUNKTE|PRÄMIENMEILEN|PRAEMIENMEILEN|MEILEN|MILES|POINTS"
_NUMBER = r"\d{1,3}(?:\.\d{3})+|\d+"
_PER_BOOKING_RE = re.compile(rf"^([+\-−])\s?({_NUMBER})\s+([A-ZÄÖÜ][\w&'\- ]*?)\s+({_UNITS})$", re.IGNORECASE)
_REDEEMED_RE = re.compile(
    rf"^EINGEL(?:OE|Ö)STE\s+(.+?)\s+({_UNITS})\s+(\d{{1,2}}\.\d{{1,2}}\.\d{{2,4}})\s+({_NUMBER})\s*-?\s+(\d[\d.]*,\d{{2}})\s*-?$",
    re.IGNORECASE,
)
_STANDING_HEADER_RE = re.compile(r"(?i)alter stand.*neuer stand")
_STANDING_RE = re.compile(
    rf"^(.+?)\s+({_UNITS})" + rf"\s+([+\-−])\s*({_NUMBER})" * 4 + "$", re.IGNORECASE,
)
_VALUE_RE = re.compile(rf"(?i)^({_NUMBER})\s+(.+?)\s+({_UNITS})\s+entsprechen\s+(\d+(?:,\d{{1,2}})?)\s+euro\b")
_PARTNER_RE = re.compile(rf"(?i)^neu gesammelte\s+(\S+(?:\s\S+)?)\s+punkte\s+über\s+.+?\s({_NUMBER})$")
_PERIOD_RE = re.compile(r"(?i)zeitraum vom\s+(\d{1,2}\.\d{1,2}\.\d{2,4})\s+bis\s+(\d{1,2}\.\d{1,2}\.\d{2,4})")


#: note of an entry that only the statement's printed figures show
STATEMENT_NOTE = "statement"


@dataclass
class PointsEntryParsed:
    program: str          # key: the program's first word and unit, upper case ("SHOP|PUNKTE")
    points: int           # signed
    kind: str             # "earned" | "redeemed" | "balance"
    booking_row: int | None = None  # source_row_index of the booking that earned them
    date_text: str | None = None    # ISO date, when not the booking's date
    value_minor: int | None = None  # a redemption's value in euro cents, as printed
    note: str | None = None         # e.g. "Prime"


@dataclass
class PointsParsed:
    entries: list[PointsEntryParsed] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)   # key -> name to show ("Shop Punkte")
    units: dict[str, str] = field(default_factory=dict)   # key -> "Punkte" / "Meilen"
    # key -> value of 100 points in cents, when the statement says so
    value_per_100: dict[str, int] = field(default_factory=dict)
    # key -> stated (opening, earned, redeemed, closing)
    standing: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "entries": [vars(e) for e in self.entries],
            "names": self.names, "units": self.units,
            "value_per_100": self.value_per_100, "standing": {k: list(v) for k, v in self.standing.items()},
        }


def _iso(text: str, reference) -> str | None:
    try:
        return parse_date_flexible(complete_date(text, reference)).isoformat()
    except DateParseError:
        return None


def _number(text: str) -> int:
    return int(text.replace(".", ""))


def _unit(text: str) -> str:
    upper = text.upper()
    if "MEILEN" in upper:
        return "Meilen"
    return {"MILES": "Miles", "POINTS": "Points"}.get(upper, "Punkte")


def _program(name: str, unit: str, out: PointsParsed, mixed_case: bool) -> str:
    """The program's key, remembering how it is named. Upper-case lines
    ("SHOP PRIME PUNKTE") name it by their first word; a line in normal
    writing ("Shop Punkte") gives the name to show."""
    words = name.split()
    unit_name = _unit(unit)
    key = f"{words[0].upper()}|{unit_name.upper()}"
    # short upper-case names are abbreviations ("DB"), longer ones are written as words ("Shop")
    shown = name if mixed_case else (words[0] if len(words[0]) <= 3 else words[0].title())
    if mixed_case or key not in out.names:
        out.names[key] = f"{shown} {unit_name}"
    out.units[key] = unit_name
    return key


def _is_mixed_case(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return any(c.islower() for c in letters) and any(c.isupper() for c in letters)


def extract_points(lines: list[str], booking_rows: list[int], reference=None) -> PointsParsed:
    """lines: the statement's text lines (indexes as source_row_index);
    booking_rows: the lines that were read as bookings."""
    out = PointsParsed()
    bookings = sorted(booking_rows)
    period_end = None
    after_standing_header = False
    b = -1  # position in bookings of the latest booking above the current line
    for index, raw in enumerate(lines):
        line = " ".join(raw.split())
        while b + 1 < len(bookings) and bookings[b + 1] < index:
            b += 1
        if not line:
            continue

        m = _PERIOD_RE.search(line)
        if m:
            period_end = _iso(m.group(2), reference)

        m = _PER_BOOKING_RE.match(line)
        if m and index not in booking_rows:
            sign, number, name, unit = m.groups()
            key = _program(name, unit, out, mixed_case=False)
            extra = " ".join(name.split()[1:]).title() or None
            points = _number(number) * (-1 if sign in "-−" else 1)
            out.entries.append(PointsEntryParsed(
                program=key, points=points, kind="earned",
                booking_row=bookings[b] if b >= 0 else None, note=extra,
            ))
            continue

        m = _REDEEMED_RE.match(line)
        if m:
            name, unit, day, number, value = m.groups()
            key = _program(name, unit, out, mixed_case=False)
            out.entries.append(PointsEntryParsed(
                program=key, points=-_number(number), kind="redeemed", date_text=_iso(day, reference),
                value_minor=int(value.replace(".", "").replace(",", "")),
            ))
            continue

        if _STANDING_HEADER_RE.search(line):
            after_standing_header = True
            continue
        m = _STANDING_RE.match(line)
        if m and after_standing_header:
            groups = m.groups()
            key = _program(groups[0], groups[1], out, mixed_case=_is_mixed_case(groups[0]))
            values = [_number(groups[i + 1]) * (-1 if groups[i] in "-−" else 1) for i in range(2, 10, 2)]
            out.standing[key] = tuple(values)  # type: ignore[assignment]
            continue

        m = _VALUE_RE.match(line)
        if m:
            count, name, unit, euros = m.groups()
            key = _program(name, unit, out, mixed_case=_is_mixed_case(name))
            cents = round(float(euros.replace(",", ".")) * 100)
            if _number(count) > 0:
                out.value_per_100[key] = round(cents * 100 / _number(count))
            continue

        m = _PARTNER_RE.match(line)
        if m:
            name, number = m.groups()
            key = _program(name, "PUNKTE", out, mixed_case=True)
            out.entries.append(PointsEntryParsed(program=key, points=_number(number), kind="earned",
                                                 date_text=period_end))
            continue

    # the statement's own figures win: what its lines don't explain (points on a
    # line not read, a redemption outside the table) is added as such, so the
    # entries add up to the printed balance
    for key, (_opening, earned, redeemed, closing) in out.standing.items():
        for kind, printed in (("earned", earned), ("redeemed", redeemed)):
            listed = sum(e.points for e in out.entries if e.program == key and e.kind == kind)
            if printed != listed:
                out.entries.append(PointsEntryParsed(program=key, points=printed - listed, kind=kind,
                                                     date_text=period_end, note=STATEMENT_NOTE))
        out.entries.append(PointsEntryParsed(program=key, points=closing, kind="balance", date_text=period_end))
    return out
