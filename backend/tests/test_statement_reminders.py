"""Which statements the app reminds of (app.services.statement_reminders)."""
from __future__ import annotations

from datetime import date

from app.db.models import ImportRecord, ImportStatus
from app.services.statement_reminders import detect_rhythm, due_statements, statement_reminders


def test_a_statement_to_the_months_end_is_due_a_few_days_after_it():
    ends = [date(2026, 8, 31), date(2026, 9, 30)]
    rhythm = detect_rhythm(ends)
    assert (rhythm.months, rhythm.month_end) == (1, True)
    assert due_statements(ends, date(2026, 10, 31)) is None  # not out yet
    assert due_statements(ends, date(2026, 11, 3)) == (rhythm, date(2026, 10, 31), 1)


def test_a_statement_mid_month_keeps_its_day():
    ends = [date(2026, 7, 15), date(2026, 8, 14), date(2026, 9, 15)]
    rhythm, newest, missing = due_statements(ends, date(2026, 11, 20))
    assert (rhythm.month_end, rhythm.day) == (False, 15)
    assert (newest, missing) == (date(2026, 11, 15), 2)


def test_a_quarterly_statement_is_due_once_a_quarter():
    ends = [date(2026, 3, 31), date(2026, 6, 30)]
    assert due_statements(ends, date(2026, 9, 1)) is None
    assert due_statements(ends, date(2026, 10, 5))[1:] == (date(2026, 9, 30), 1)


def test_a_partial_export_does_not_skip_a_period():
    # An export made on the 27th still counts as that month's statement.
    ends = [date(2026, 8, 31), date(2026, 9, 27)]
    assert due_statements(ends, date(2026, 10, 1)) is None
    assert due_statements(ends, date(2026, 11, 4))[1] == date(2026, 10, 31)


def test_an_account_long_without_statements_is_left_alone():
    assert due_statements([date(2025, 1, 31), date(2025, 2, 28)], date(2026, 11, 17)) is None


def test_reminders_skip_archived_accounts_and_open_imports(session, checking_account, savings_account):
    for account, status in ((checking_account, ImportStatus.IMPORTED), (savings_account, ImportStatus.PENDING)):
        session.add(ImportRecord(filename="a.csv", stored_path="a.csv", file_checksum=f"c{account.id}",
                                 account_id=account.id, status=status, period_end=date(2026, 9, 30)))
    session.commit()
    [reminder] = statement_reminders(session, date(2026, 11, 17))
    assert (reminder.account_id, reminder.period_end, reminder.missing) == (checking_account.id, date(2026, 10, 31), 1)
    checking_account.is_archived = True
    session.add(checking_account)
    session.commit()
    assert statement_reminders(session, date(2026, 11, 17)) == []


def test_the_reminders_are_served(client):
    response = client.get("/api/accounts/statement-reminders")
    assert response.status_code == 200
    assert response.json() == []
