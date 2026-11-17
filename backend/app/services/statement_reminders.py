"""Which statements should be ready to download by now.

Statements come in a rhythm: a bank statement every month up to its last
day, a card statement around the 15th, a quarterly one up to the end of a
quarter... The rhythm of an account is read from the statements already
imported for it: how many months lie between their period ends, and on
which day they end (the month's last day, or a fixed day). Counting on from
the newest one tells which statements have come out since.
"""
from __future__ import annotations

import calendar
import itertools
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from sqlmodel import Session, select

from app.db.models import Account, AccountType, CreditCardStatement, ImportRecord, ImportStatus

# A statement is ready the day after its period ends.
ISSUE_DELAY_DAYS = 1
# A period end this close to the newest one is still the same statement
# (e.g. an export made a few days before the month's end).
SAME_PERIOD_DAYS = 7
# An account with no statement for this many periods is no longer used.
DORMANT_AFTER_PERIODS = 6
# Only the most recent statements decide the day: banks change it now and then.
RHYTHM_SAMPLE = 6


@dataclass(frozen=True)
class Rhythm:
    months: int      # 1 monthly, 3 quarterly, ...
    month_end: bool  # ends on the last day of the month
    day: int         # otherwise on this day (or the month's last, if shorter)


@dataclass(frozen=True)
class StatementReminder:
    account_id: int
    account_name: str
    account_type: AccountType
    last_period_end: date  # the newest statement imported ends here
    period_end: date       # the newest statement ready by now ends here
    missing: int           # statements ready but not imported
    rhythm_months: int
    month_end: bool
    day: int


def _month_index(d: date) -> int:
    return d.year * 12 + d.month - 1


def _period_end(index: int, rhythm: Rhythm) -> date:
    year, month = divmod(index, 12)
    last = calendar.monthrange(year, month + 1)[1]
    return date(year, month + 1, last if rhythm.month_end else min(rhythm.day, last))


def detect_rhythm(ends: list[date]) -> Rhythm:
    ends = sorted(set(ends))
    gaps = [g for a, b in itertools.pairwise(ends) if (g := _month_index(b) - _month_index(a)) > 0]
    months = max(1, round(statistics.median(gaps))) if gaps else 1
    recent = ends[-RHYTHM_SAMPLE:]
    at_month_end = sum(d.day == calendar.monthrange(d.year, d.month)[1] for d in recent)
    return Rhythm(
        months=months,
        month_end=at_month_end * 2 >= len(recent),
        day=round(statistics.median(d.day for d in recent)),
    )


def due_statements(ends: list[date], today: date) -> tuple[Rhythm, date, int] | None:
    """The rhythm, the end of the newest statement ready by `today` and how
    many are ready since the newest of `ends` — None when none is (or so
    many that the account is no longer used)."""
    rhythm = detect_rhythm(ends)
    last = max(ends)
    index = _month_index(last)
    if rhythm.months > 1:
        index += rhythm.months
    else:
        while _period_end(index, rhythm) <= last + timedelta(days=SAME_PERIOD_DAYS):
            index += 1
    newest, count = None, 0
    while _period_end(index, rhythm) + timedelta(days=ISSUE_DELAY_DAYS) <= today:
        newest, count = _period_end(index, rhythm), count + 1
        if count > DORMANT_AFTER_PERIODS:
            return None
        index += rhythm.months
    return (rhythm, newest, count) if newest else None


def statement_reminders(session: Session, today: date) -> list[StatementReminder]:
    # A card statement's own period is the better date than the file's.
    card_ends = dict(session.exec(
        select(CreditCardStatement.import_id, CreditCardStatement.statement_period_end)
        .where(CreditCardStatement.statement_period_end.is_not(None))  # type: ignore[union-attr]
    ).all())
    ends_by_account: dict[int, list[date]] = {}
    for import_id, account_id, period_end in session.exec(
        select(ImportRecord.id, ImportRecord.account_id, ImportRecord.period_end)
        .where(ImportRecord.status == ImportStatus.IMPORTED, ImportRecord.account_id.is_not(None))  # type: ignore[union-attr]
    ).all():
        end = card_ends.get(import_id) or period_end
        if end:
            ends_by_account.setdefault(account_id, []).append(end)

    reminders = []
    accounts = session.exec(select(Account).where(Account.is_archived == False).order_by(Account.name)).all()  # noqa: E712
    for account in accounts:
        ends = ends_by_account.get(account.id)
        if not ends or not (due := due_statements(ends, today)):
            continue
        rhythm, newest, count = due
        reminders.append(StatementReminder(
            account_id=account.id, account_name=account.name, account_type=account.account_type,
            last_period_end=max(ends), period_end=newest, missing=count,
            rhythm_months=rhythm.months, month_end=rhythm.month_end, day=rhythm.day,
        ))
    return reminders
