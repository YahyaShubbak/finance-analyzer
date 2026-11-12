"""Bonus points from card statements: stored on import, shown in the
"Bonus points" view (app/api/routes/points.py).

What a statement prints is kept as entries: points a booking earned (linked
to that booking), points redeemed, and the statement's stated balance. The
current standing is the latest stated balance plus what was earned and
redeemed after it — or, for programs whose statements state no balance,
the sum of everything earned and redeemed.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date

from sqlmodel import Session, delete, func, select

from app.config import settings
from app.db.chunks import chunked
from app.db.models import ImportRecord, ImportStatus, PointsEntry, PointsProgram, RawTransaction, Transaction
from app.importers.base import ParsedImport, ParseOptions
from app.services.import_reading import parse_file
from app.services.import_staging import stored_import_path

logger = logging.getLogger("finance")

#: raise to read the stored statements again on the next start (new formats understood)
POINTS_VERSION = "2"
#: in the data folder: the POINTS_VERSION the stored statements were last read with
POINTS_MARKER = ".points_version"


def store_points(session: Session, record: ImportRecord, parsed: ParsedImport, row_tx: dict[int, int]) -> int:
    """Keep the points a statement prints. row_tx: a booking's
    source_row_index -> its transaction (new, or the one it duplicated)."""
    points = parsed.points or {}
    entries = points.get("entries") or []
    if not entries:
        return 0
    dates = {t.source_row_index: t.parsed_date for t in parsed.transactions if t.parsed_date}
    fallback = record.period_end or record.imported_at.date()
    programs: dict[str, PointsProgram] = {}
    for key in {e["program"] for e in entries}:
        program = session.exec(select(PointsProgram).where(PointsProgram.key == key)).first()
        if program is None:
            program = PointsProgram(key=key, name=(points.get("names") or {}).get(key, key.split("|")[0].title()),
                                    unit=(points.get("units") or {}).get(key, "Punkte"))
        value = (points.get("value_per_100") or {}).get(key)
        if value and not program.value_set_by_user:
            program.value_per_100 = int(value)
        session.add(program)
        session.flush()
        programs[key] = program
    for e in entries:
        row = e.get("booking_row")
        when = e.get("date_text") or (dates.get(row) if row is not None else None)
        session.add(PointsEntry(
            program_id=programs[e["program"]].id,
            import_id=record.id,
            transaction_id=row_tx.get(row) if row is not None else None,
            entry_date=date.fromisoformat(when) if when else fallback,
            points=int(e["points"]),
            kind=e["kind"],
            value_minor=e.get("value_minor"),
            note=e.get("note"),
        ))
    return len(entries)


def forget_points(session: Session, import_id: int, removed_transaction_ids: set[int]) -> None:
    """An import is removed: its points go, other points lose removed bookings."""
    session.exec(delete(PointsEntry).where(PointsEntry.import_id == import_id))
    for chunk in chunked(list(removed_transaction_ids)):
        for entry in session.exec(select(PointsEntry).where(PointsEntry.transaction_id.in_(chunk))).all():
            entry.transaction_id = None
            session.add(entry)
    session.flush()
    used = set(session.exec(select(PointsEntry.program_id).distinct()).all())
    for program in session.exec(select(PointsProgram)).all():
        if program.id not in used and not program.value_set_by_user:
            session.delete(program)


def _row_transactions(session: Session, import_id: int) -> dict[int, int]:
    """For an imported file: each row's booking (its own, or the one it duplicated)."""
    out: dict[int, int] = {}
    raws = session.exec(select(RawTransaction).where(RawTransaction.import_id == import_id)).all()
    by_raw = {}
    for chunk in chunked([r.id for r in raws]):
        by_raw.update({t.raw_transaction_id: t.id for t in session.exec(
            select(Transaction).where(Transaction.raw_transaction_id.in_(chunk))).all()})
    for raw in raws:
        if raw.id in by_raw:
            out[raw.source_row_index] = by_raw[raw.id]
        elif raw.duplicate_of_transaction_id is not None:
            out[raw.source_row_index] = raw.duplicate_of_transaction_id
    return out


def backfill_points(session: Session, force: bool = False) -> None:
    """On start-up, once per POINTS_VERSION (force: after restoring a
    backup): read the points of the PDF statements imported before, or with
    an older reader. Never keeps the app from starting."""
    marker = settings.data_dir / POINTS_MARKER
    try:
        if not force and marker.exists() and marker.read_text(encoding="utf-8").strip() == POINTS_VERSION:
            return
        records = session.exec(select(ImportRecord).where(ImportRecord.status == ImportStatus.IMPORTED)).all()
        found = 0
        for record in records:
            if not record.filename.lower().endswith(".pdf"):
                continue
            path = stored_import_path(record.stored_path)
            if path is None or not path.exists():
                continue
            try:
                info = json.loads(record.source_info_json) if record.source_info_json else {}
                parsed = parse_file(path, original_filename=record.filename,
                                    options=ParseOptions.from_dict(info.get("options")) if info.get("options") else None)
            except Exception:  # noqa: BLE001 — that statement's points just stay unknown
                logger.debug("Could not read %s for points", record.filename, exc_info=True)
                continue
            session.exec(delete(PointsEntry).where(PointsEntry.import_id == record.id))
            found += store_points(session, record, parsed, _row_transactions(session, record.id))
        session.commit()
        marker.write_text(POINTS_VERSION, encoding="utf-8")
        if found:
            logger.info("Read %d bonus point entries from imported statements", found)
    except Exception:  # noqa: BLE001
        session.rollback()
        logger.exception("Could not read bonus points from imported statements")


def _month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def points_overview(session: Session) -> list[dict]:
    """Per program: standing and its value, what was earned and redeemed
    per month, the effective cashback, where the points came from."""
    out = []
    today = date.today()
    for program in session.exec(select(PointsProgram).order_by(PointsProgram.name)).all():
        entries = session.exec(
            select(PointsEntry).where(PointsEntry.program_id == program.id).order_by(PointsEntry.entry_date, PointsEntry.id)
        ).all()
        if not entries:
            continue
        flows = [e for e in entries if e.kind != "balance"]
        stated = sorted((e for e in entries if e.kind == "balance"), key=lambda e: (e.entry_date, e.id))
        anchor = stated[-1] if stated else None

        def standing_at(day: date, stated=stated, flows=flows) -> int:
            """From the latest printed balance up to `day` (before the first one: back from it)."""
            if not stated:
                return sum(e.points for e in flows if e.entry_date <= day)
            before = [a for a in stated if a.entry_date <= day]
            if before:
                base = before[-1]
                return base.points + sum(e.points for e in flows if base.entry_date < e.entry_date <= day)
            first = stated[0]
            return first.points - sum(e.points for e in flows if day < e.entry_date <= first.entry_date)

        last_day = max(e.entry_date for e in entries)
        balance = standing_at(max(last_day, today))

        months: dict[str, dict] = defaultdict(lambda: {"earned": 0, "redeemed": 0})
        for e in flows:
            months[_month(e.entry_date)]["earned" if e.kind == "earned" else "redeemed"] += e.points
        first = min(e.entry_date for e in entries)
        series = []
        y, m = first.year, first.month
        while (y, m) <= (last_day.year, last_day.month):
            key = f"{y:04d}-{m:02d}"
            month_end = date(y + (m == 12), m % 12 + 1, 1)
            series.append({"month": key, **months.get(key, {"earned": 0, "redeemed": 0}),
                           "balance": standing_at(date.fromordinal(month_end.toordinal() - 1))})
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)

        earned = sum(e.points for e in flows if e.kind == "earned")
        redeemed = sum(e.points for e in flows if e.kind == "redeemed")
        year_earned = sum(e.points for e in flows if e.kind == "earned" and e.entry_date.year == today.year)
        year_redeemed = sum(e.points for e in flows if e.kind == "redeemed" and e.entry_date.year == today.year)

        # cashback: the value of the points purchases earned, against the purchases of the
        # statements that earned them (refunds and the points they take back are left out)
        import_ids = {e.import_id for e in flows if e.kind == "earned"}
        spend = 0
        # each card's spending over the periods of these statements, overlaps counted once
        periods: dict[int, list[tuple[date, date]]] = defaultdict(list)
        for record in (session.get(ImportRecord, i) for i in import_ids):
            if record is not None and record.account_id is not None and record.period_start and record.period_end:
                periods[record.account_id].append((record.period_start, record.period_end))
        for account_id, spans in periods.items():
            merged: list[list[date]] = []
            for begin, finish in sorted(spans):
                if merged and begin <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], finish)
                else:
                    merged.append([begin, finish])
            for begin, finish in merged:
                spend += -(session.exec(select(func.coalesce(func.sum(Transaction.amount_minor), 0)).where(
                    Transaction.account_id == account_id, Transaction.amount_minor < 0,
                    Transaction.is_transfer == False, Transaction.is_duplicate == False,  # noqa: E712
                    Transaction.transaction_date >= begin, Transaction.transaction_date <= finish,
                )).one() or 0)
        earned_value = sum(e.points for e in flows if e.kind == "earned" and e.points > 0) * program.value_per_100 / 100
        cashback = round(earned_value / spend * 100, 2) if spend > 0 else None

        linked = [e for e in flows if e.transaction_id is not None]
        txs = {}
        for chunk in chunked(list({e.transaction_id for e in linked})):
            txs.update({t.id: t for t in session.exec(select(Transaction).where(Transaction.id.in_(chunk))).all()})
        by_merchant: dict[str, dict] = defaultdict(lambda: {"points": 0, "bookings": 0, "spent_minor": 0})
        per_booking: dict[int, int] = defaultdict(int)
        for e in linked:
            if e.transaction_id in txs:
                per_booking[e.transaction_id] += e.points
        for tx_id, pts in per_booking.items():
            tx = txs[tx_id]
            row = by_merchant[tx.merchant or tx.normalized_description]
            row["points"] += pts
            row["bookings"] += 1
            row["spent_minor"] += -tx.amount_minor
        merchants = sorted(({"merchant": k, **v} for k, v in by_merchant.items()), key=lambda r: -r["points"])[:10]
        recent = sorted(per_booking.items(), key=lambda item: (txs[item[0]].transaction_date, item[0]), reverse=True)[:30]

        out.append({
            "id": program.id,
            "name": program.name,
            "unit": program.unit,
            "value_per_100": program.value_per_100,
            "value_set_by_user": program.value_set_by_user,
            "balance": balance,
            "balance_value_minor": round(balance * program.value_per_100 / 100),
            "balance_stated": anchor is not None,
            "balance_as_of": (anchor.entry_date if anchor else last_day).isoformat(),
            "earned": earned,
            "redeemed": redeemed,
            "earned_this_year": year_earned,
            "redeemed_this_year": year_redeemed,
            "cashback_percent": cashback,
            "months": series,
            "merchants": merchants,
            "redemptions": [{"date": e.entry_date.isoformat(), "points": e.points, "value_minor": e.value_minor}
                            for e in reversed(flows) if e.kind == "redeemed"],
            "bookings": [{
                "transaction_id": tx_id, "date": txs[tx_id].transaction_date.isoformat(),
                "merchant": txs[tx_id].merchant or txs[tx_id].normalized_description,
                "amount_minor": txs[tx_id].amount_minor, "currency": txs[tx_id].currency, "points": pts,
            } for tx_id, pts in recent],
        })
    return out


def points_by_transaction(session: Session, transaction_ids: list[int]) -> dict[int, int]:
    """The points each booking earned (for the badge in the transaction list)."""
    out: dict[int, int] = {}
    for chunk in chunked(transaction_ids):
        rows = session.exec(
            select(PointsEntry.transaction_id, func.sum(PointsEntry.points))
            .where(PointsEntry.transaction_id.in_(chunk), PointsEntry.kind == "earned")
            .group_by(PointsEntry.transaction_id)
        ).all()
        out.update({tx_id: int(total) for tx_id, total in rows if tx_id is not None})
    return out
