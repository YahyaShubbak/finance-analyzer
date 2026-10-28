from datetime import date

from sqlmodel import select

from app.db.models import RawTransaction, Transaction, TransactionType
from app.services.duplicate_detection import compute_duplicate_fingerprint


def test_amount_stored_as_exact_integer_minor_units(session, checking_account):
    raw = RawTransaction(
        import_id=_fake_import(session, checking_account.id),
        source_row_index=0,
        original_amount_text="-45,67",
        original_description="Test",
        original_date_text="02.01.2026",
    )
    session.add(raw)
    session.commit()
    session.refresh(raw)

    tx = Transaction(
        raw_transaction_id=raw.id,
        account_id=checking_account.id,
        transaction_date=date(2026, 1, 2),
        normalized_description="Test",
        amount_minor=-4567,
        currency="EUR",
        transaction_type=TransactionType.EXPENSE,
        duplicate_fingerprint=compute_duplicate_fingerprint(
            checking_account.id, "2026-01-02", -4567, "Test"
        ),
    )
    session.add(tx)
    session.commit()
    session.refresh(tx)

    fetched = session.exec(select(Transaction).where(Transaction.id == tx.id)).one()
    assert fetched.amount_minor == -4567
    assert isinstance(fetched.amount_minor, int)


def test_duplicate_fingerprint_ignores_varying_reference_numbers():
    fp1 = compute_duplicate_fingerprint(1, "2026-01-02", -4567, "REWE SAGT DANKE 12345")
    fp2 = compute_duplicate_fingerprint(1, "2026-01-02", -4567, "REWE SAGT DANKE 98765")
    assert fp1 == fp2  # long numeric refs stripped before hashing


def test_duplicate_fingerprint_differs_on_amount():
    fp1 = compute_duplicate_fingerprint(1, "2026-01-02", -4567, "REWE")
    fp2 = compute_duplicate_fingerprint(1, "2026-01-02", -4500, "REWE")
    assert fp1 != fp2


def _fake_import(session, account_id: int) -> int:
    from app.db.models import DocumentType, ImportRecord, ImportStatus

    imp = ImportRecord(
        filename="test.csv",
        stored_path="imports/test.csv",
        file_checksum="deadbeef",
        document_type=DocumentType.BANK_STATEMENT,
        account_id=account_id,
        status=ImportStatus.IMPORTED,
    )
    session.add(imp)
    session.commit()
    session.refresh(imp)
    return imp.id
