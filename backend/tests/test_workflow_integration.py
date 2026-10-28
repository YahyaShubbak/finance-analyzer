"""End-to-end workflow test (spec sections: reconciliation workflow +
the explicit no-double-counting accounting requirement):

    Bank statement (checking, salary + CC payment)
          -> Credit-card statement (import, with declared total)
          -> Individual CC transactions (the real purchases/expenses)
          -> Reconciliation
          -> Overall analytics must count the €100 purchase exactly once.
"""
from __future__ import annotations

from sqlmodel import select

from app.reconciliation.engine import reconcile_statement
from app.services.analytics_service import compute_totals
from app.services.import_service import commit_parsed_import, parse_file
from tests.pdf_fixtures import write_text_pdf


def test_full_chain_bank_to_reconciliation_no_double_counting(
    session, checking_account, credit_card_account, tmp_path
):
    # 1. The user spends €100 on their credit card during March.
    cc_pdf = write_text_pdf(tmp_path / "cc_march.pdf", [
        "Credit Card Statement",
        "VISA ending 1234",
        "Statement Period: 01.03.2026 - 10.03.2026",
        "02.03.2026 Amazon.de 100.00 EUR",
        "Statement Total: 100.00 EUR",
    ])
    cc_result = commit_parsed_import(
        session, parse_file(cc_pdf), credit_card_account.id, "imports/cc_march.pdf"
    )
    assert cc_result.transactions_created == 1
    assert cc_result.credit_card_statement is not None

    # 2. The following month, the checking account shows the salary AND the
    #    credit-card bill being paid off in full.
    bank_pdf = write_text_pdf(tmp_path / "checking_march.pdf", [
        "Bank Statement",
        "Checking Account",
        "Statement Period: 01.03.2026 - 15.03.2026",
        "05.03.2026 Salary 2500.00 EUR",
        "12.03.2026 Credit Card Payment -100.00 EUR",
    ])
    bank_result = commit_parsed_import(
        session, parse_file(bank_pdf), checking_account.id, "imports/checking_march.pdf"
    )
    assert bank_result.transactions_created == 2

    # 3+4. The bank import itself reconciles the pending statement: the
    #    debit matches the statement total exactly and is the only
    #    candidate, so it is linked as the statement's settlement — the
    #    €100 is never double-counted, not even briefly.
    rec = reconcile_statement(session, cc_result.credit_card_statement.id)
    assert rec.status.value == "reconciled"
    assert rec.bank_debit_transaction_id is not None

    # 5. After reconciliation, the bank debit is excluded from totals — the
    #    €100 CC purchase is counted exactly once.
    totals = compute_totals(session)
    assert totals.expenses_minor == 10000  # only the original Amazon purchase
    assert totals.income_minor == 250000  # salary unaffected

    # 6. Full audit trail still resolves back to source documents.
    from app.db.models import Transaction as TxModel
    bank_debit = session.get(TxModel, rec.bank_debit_transaction_id)
    assert bank_debit.is_transfer is True
    assert bank_debit.transaction_type.value == "transfer"
    assert bank_debit.raw_transaction.import_record.filename == "checking_march.pdf"

    cc_purchase = [
        t for t in session.exec(
            select(TxModel).where(TxModel.account_id == credit_card_account.id)
        ).all()
    ][0]
    assert cc_purchase.raw_transaction.import_record.filename == "cc_march.pdf"
    assert cc_purchase.raw_transaction.original_description == "Amazon.de"
