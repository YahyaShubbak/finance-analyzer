"""The cash wallet (app.services.cash_service)."""
from __future__ import annotations

from datetime import date

from sqlmodel import select

from app.db.models import Account, AccountType, ImportRecord, RawTransaction, Transaction, TransactionType
from app.services import cash_service
from app.services.transfer_detection_service import run_transfer_detection


def _booking(session, account, amount, category, day=date(2026, 11, 2)):
    record = ImportRecord(filename="s.csv", stored_path="s.csv", file_checksum=f"c{amount}{category}", account_id=account.id)
    session.add(record)
    session.flush()
    raw = RawTransaction(import_id=record.id, source_row_index=1)
    session.add(raw)
    session.flush()
    tx = Transaction(raw_transaction_id=raw.id, account_id=account.id, transaction_date=day,
                     normalized_description=category, category=category, amount_minor=amount,
                     transaction_type=TransactionType.EXPENSE if amount < 0 else TransactionType.INCOME,
                     duplicate_fingerprint=f"f{amount}{category}")
    session.add(tx)
    session.commit()
    return tx


def _wallet(session):
    wallet = Account(name="Wallet", account_type=AccountType.CASH)
    session.add(wallet)
    session.commit()
    return wallet


def test_a_withdrawal_moves_into_the_wallet_and_back_without_one(session, checking_account):
    withdrawal = _booking(session, checking_account, -10000, "Cash")
    wallet = _wallet(session)
    assert cash_service.sync_withdrawals(session) == 1
    assert withdrawal.transaction_type == TransactionType.TRANSFER
    assert cash_service.wallet_balance(session, wallet.id).balance_minor == 10000
    wallet.is_archived = True
    session.add(wallet)
    session.commit()
    cash_service.sync_withdrawals(session)
    assert withdrawal.transaction_type == TransactionType.EXPENSE and not withdrawal.is_transfer


def test_entries_and_a_count_give_the_wallet_balance(session, checking_account):
    _booking(session, checking_account, -10000, "Cash")
    wallet = _wallet(session)
    cash_service.sync_withdrawals(session)
    cash_service.add_entry(session, wallet.id, date(2026, 11, 3), -2340, "Groceries", "market")
    cash_service.add_entry(session, wallet.id, date(2026, 11, 4), 5000, "Other Income", "debt paid back")
    assert cash_service.wallet_balance(session, wallet.id).balance_minor == 12660
    gap = cash_service.count_wallet(session, wallet.id, date(2026, 11, 5), 12000, "count")
    assert (gap.amount_minor, gap.category, gap.transaction_type) == (-660, "Cash", TransactionType.EXPENSE)
    assert cash_service.count_wallet(session, wallet.id, date(2026, 11, 5), 12000, "count") is None
    cash_service.delete_entry(session, wallet.id, gap.id)
    assert cash_service.wallet_balance(session, wallet.id).balance_minor == 12660


def test_a_cash_entry_is_never_paired_as_a_transfer(session, checking_account):
    _booking(session, checking_account, -5000, "Groceries")
    wallet = _wallet(session)
    cash_service.add_entry(session, wallet.id, date(2026, 11, 2), 5000, "Other Income", "present")
    run_transfer_detection(session, full_rescan=True)
    assert not any(t.is_transfer for t in session.exec(select(Transaction)).all())


def test_cash_entries_over_the_api(client):
    wallet = client.post("/api/accounts", json={"name": "Wallet", "account_type": "cash"}).json()
    r = client.post(f"/api/accounts/{wallet['id']}/cash-entries",
                    json={"transaction_date": "2026-11-03", "amount_minor": -1500, "category": "Groceries"})
    assert r.status_code == 200 and r.json()["balance_minor"] == -1500
    bad = client.post(f"/api/accounts/{wallet['id']}/cash-entries",
                      json={"transaction_date": "2026-11-03", "amount_minor": -1, "category": "Nope"})
    assert bad.status_code == 422
    assert client.post(f"/api/accounts/{wallet['id']}/cash-count",
                       json={"counted_on": "2026-11-04", "counted_minor": 0}).json()["balance_minor"] == 0
    assert all(i["filename"] != "manual" for i in client.get("/api/imports").json())
