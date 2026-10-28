"""Reconciliation engine test matrix.

For precision and speed, these tests construct the DB rows directly
(account, import, raw+normalized transactions, credit-card statement)
rather than going through the PDF pipeline for every scenario — the PDF
pipeline itself is covered separately in test_pdf_importer.py and the
full end-to-end chain in test_workflow_integration.py.
"""
from __future__ import annotations

import json
from datetime import date

from app.db.models import (
    CreditCardStatement,
    DocumentType,
    ImportRecord,
    ImportStatus,
    RawTransaction,
    Transaction,
    TransactionType,
)
from app.reconciliation.engine import reconcile_statement, resolve_reconciliation
from app.services.duplicate_detection import compute_duplicate_fingerprint


def _make_import(session, account_id, filename="cc_statement.pdf", checksum="abc"):
    imp = ImportRecord(
        filename=filename,
        stored_path=f"imports/{filename}",
        file_checksum=checksum,
        document_type=DocumentType.CREDIT_CARD_STATEMENT,
        account_id=account_id,
        status=ImportStatus.IMPORTED,
    )
    session.add(imp)
    session.commit()
    session.refresh(imp)
    return imp


def _add_cc_transaction(session, account_id, import_id, day, amount_minor, description="Purchase", is_duplicate=False, duplicate_of_id=None):
    raw = RawTransaction(
        import_id=import_id, source_row_index=day, original_description=description,
        original_amount_text=str(amount_minor / 100),
    )
    session.add(raw)
    session.commit()
    session.refresh(raw)

    tx = Transaction(
        raw_transaction_id=raw.id,
        account_id=account_id,
        transaction_date=date(2026, 3, day),
        normalized_description=description,
        amount_minor=amount_minor,
        currency="EUR",
        transaction_type=TransactionType.EXPENSE if amount_minor < 0 else TransactionType.INCOME,
        duplicate_fingerprint=compute_duplicate_fingerprint(account_id, f"2026-03-{day:02d}", amount_minor, description),
        is_duplicate=is_duplicate,
        duplicate_of_id=duplicate_of_id,
    )
    session.add(tx)
    session.commit()
    session.refresh(tx)
    return tx


def _add_bank_debit(session, account_id, day, amount_minor, description="Credit Card Payment"):
    raw = RawTransaction(import_id=_make_import(session, account_id, filename=f"bank_{day}.csv", checksum=f"bankchk{day}{amount_minor}").id,
                          source_row_index=0, original_description=description)
    session.add(raw)
    session.commit()
    session.refresh(raw)

    tx = Transaction(
        raw_transaction_id=raw.id,
        account_id=account_id,
        transaction_date=date(2026, 3, day),
        normalized_description=description,
        amount_minor=amount_minor,
        currency="EUR",
        transaction_type=TransactionType.EXPENSE,
        duplicate_fingerprint=compute_duplicate_fingerprint(account_id, f"2026-03-{day:02d}", amount_minor, description),
    )
    session.add(tx)
    session.commit()
    session.refresh(tx)
    return tx


def _make_statement(session, cc_account_id, import_id, total_minor, other_totals=None, period_end=date(2026, 3, 10)):
    stmt = CreditCardStatement(
        account_id=cc_account_id,
        import_id=import_id,
        statement_period_start=date(2026, 3, 1),
        statement_period_end=period_end,
        statement_total_minor=total_minor,
        other_totals_json=json.dumps(other_totals) if other_totals else None,
        currency="EUR",
    )
    session.add(stmt)
    session.commit()
    session.refresh(stmt)
    return stmt


# ---------------------------------------------------------------------------

def test_perfectly_reconciled(session, checking_account, credit_card_account):
    imp = _make_import(session, credit_card_account.id)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 2, -10000)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 5, -20000)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 10, -4237)
    stmt = _make_statement(session, credit_card_account.id, imp.id, total_minor=34237)
    _add_bank_debit(session, checking_account.id, 15, -34237)

    rec = reconcile_statement(session, stmt.id, auto_match=True)

    assert rec.transaction_total_minor == 34237
    assert rec.diff_transactions_vs_statement_minor == 0
    assert rec.diff_statement_vs_bank_minor == 0
    assert rec.status.value == "reconciled"
    assert rec.explanation_tags_json is None


def test_transaction_total_not_equal_statement_total(session, checking_account, credit_card_account):
    imp = _make_import(session, credit_card_account.id)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 2, -10000)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 5, -20000)
    # statement declares 34237 but only 30000 in captured transactions -> a
    # transaction is missing from our extraction (e.g. a PDF parsing gap).
    stmt = _make_statement(session, credit_card_account.id, imp.id, total_minor=34237)
    _add_bank_debit(session, checking_account.id, 15, -34237)

    rec = reconcile_statement(session, stmt.id, auto_match=True)

    assert rec.transaction_total_minor == 30000
    assert rec.diff_transactions_vs_statement_minor == 4237
    assert rec.diff_statement_vs_bank_minor == 0
    assert rec.status.value == "mismatch"
    # No evidence available to explain this gap -> no invented tags.
    assert rec.explanation_tags_json is None


def test_statement_total_not_equal_bank_debit_partial_payment(session, checking_account, credit_card_account):
    imp = _make_import(session, credit_card_account.id)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 2, -10000)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 5, -20000)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 10, -4237)
    stmt = _make_statement(session, credit_card_account.id, imp.id, total_minor=34237)
    bank_tx = _add_bank_debit(session, checking_account.id, 15, -30000)  # paid less than owed

    # Not an exact match -> never linked automatically, only suggested.
    auto = reconcile_statement(session, stmt.id, auto_match=True)
    assert auto.bank_debit_transaction_id is None
    rec = reconcile_statement(session, stmt.id, bank_debit_transaction_id=bank_tx.id)

    assert rec.diff_transactions_vs_statement_minor == 0
    assert rec.diff_statement_vs_bank_minor == -4237
    assert rec.status.value == "mismatch"
    assert "partial_payment" in json.loads(rec.explanation_tags_json)


def test_both_mismatches_simultaneously(session, checking_account, credit_card_account):
    imp = _make_import(session, credit_card_account.id)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 2, -10000)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 5, -20000)
    stmt = _make_statement(session, credit_card_account.id, imp.id, total_minor=34237)  # missing tx
    bank_tx = _add_bank_debit(session, checking_account.id, 15, -32000)  # also a partial payment

    # Not an exact match -> never linked automatically, only suggested.
    auto = reconcile_statement(session, stmt.id, auto_match=True)
    assert auto.bank_debit_transaction_id is None
    rec = reconcile_statement(session, stmt.id, bank_debit_transaction_id=bank_tx.id)

    assert rec.diff_transactions_vs_statement_minor == 4237
    assert rec.diff_statement_vs_bank_minor == -2237
    assert rec.status.value == "mismatch"
    tags = json.loads(rec.explanation_tags_json)
    assert "partial_payment" in tags


def test_refund_line_nets_correctly_no_false_mismatch(session, checking_account, credit_card_account):
    imp = _make_import(session, credit_card_account.id)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 2, -20000, description="Amazon")
    _add_cc_transaction(session, credit_card_account.id, imp.id, 8, 5000, description="Amazon Refund")
    _add_cc_transaction(session, credit_card_account.id, imp.id, 10, -10000, description="REWE")
    stmt = _make_statement(session, credit_card_account.id, imp.id, total_minor=25000)
    _add_bank_debit(session, checking_account.id, 15, -25000)

    rec = reconcile_statement(session, stmt.id, auto_match=True)

    assert rec.transaction_total_minor == 25000  # -200+50-100 = -250 -> owed 250.00
    assert rec.status.value == "reconciled"


def test_fee_explains_statement_vs_bank_diff(session, checking_account, credit_card_account):
    imp = _make_import(session, credit_card_account.id)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 2, -30000)
    stmt = _make_statement(session, credit_card_account.id, imp.id, total_minor=30000, other_totals={"fee": 500})
    bank_tx = _add_bank_debit(session, checking_account.id, 15, -30500)  # bank charged statement + fee

    # Not an exact match -> never linked automatically, only suggested.
    auto = reconcile_statement(session, stmt.id, auto_match=True)
    assert auto.bank_debit_transaction_id is None
    rec = reconcile_statement(session, stmt.id, bank_debit_transaction_id=bank_tx.id)

    assert rec.diff_statement_vs_bank_minor == 500
    tags = json.loads(rec.explanation_tags_json)
    assert "fee" in tags


def test_interest_explains_statement_vs_bank_diff(session, checking_account, credit_card_account):
    imp = _make_import(session, credit_card_account.id)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 2, -30000)
    stmt = _make_statement(session, credit_card_account.id, imp.id, total_minor=30000, other_totals={"interest": 1200})
    bank_tx = _add_bank_debit(session, checking_account.id, 15, -31200)

    # Not an exact match -> never linked automatically, only suggested.
    auto = reconcile_statement(session, stmt.id, auto_match=True)
    assert auto.bank_debit_transaction_id is None
    rec = reconcile_statement(session, stmt.id, bank_debit_transaction_id=bank_tx.id)

    assert rec.diff_statement_vs_bank_minor == 1200
    tags = json.loads(rec.explanation_tags_json)
    assert "interest" in tags


def test_card_payment_line_excluded_from_transaction_total(session, checking_account, credit_card_account):
    """The statement's "payment received" line is the card being paid off
    (a transfer), not a refund — it must not reduce the charged total."""
    imp = _make_import(session, credit_card_account.id)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 2, -10000, description="Amazon")
    _add_cc_transaction(session, credit_card_account.id, imp.id, 5, -20000, description="REWE")
    payment = _add_cc_transaction(session, credit_card_account.id, imp.id, 6, 25000, description="Payment received")
    payment.is_transfer = True
    payment.transaction_type = TransactionType.TRANSFER
    session.add(payment)
    session.commit()
    stmt = _make_statement(session, credit_card_account.id, imp.id, total_minor=30000)

    rec = reconcile_statement(session, stmt.id, auto_match=True)

    assert rec.transaction_total_minor == 30000
    assert rec.diff_transactions_vs_statement_minor == 0

def test_currency_mismatch_flagged(session, checking_account, credit_card_account):
    credit_card_account.currency = "USD"
    session.add(credit_card_account)
    session.commit()

    imp = _make_import(session, credit_card_account.id)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 2, -30000)
    stmt = _make_statement(session, credit_card_account.id, imp.id, total_minor=30000)
    stmt.currency = "USD"
    session.add(stmt)
    session.commit()

    # Bank debit is in EUR (checking account currency) but pays a USD statement.
    bank_tx = _add_bank_debit(session, checking_account.id, 15, -27500)  # FX-converted amount

    # Not an exact match -> never linked automatically, only suggested.
    auto = reconcile_statement(session, stmt.id, auto_match=True)
    assert auto.bank_debit_transaction_id is None
    rec = reconcile_statement(session, stmt.id, bank_debit_transaction_id=bank_tx.id)

    tags = json.loads(rec.explanation_tags_json)
    assert "currency_conversion" in tags


def test_no_bank_debit_found_is_pending_not_mismatch(session, checking_account, credit_card_account):
    imp = _make_import(session, credit_card_account.id)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 2, -30000)
    stmt = _make_statement(session, credit_card_account.id, imp.id, total_minor=30000)
    # No bank statement imported yet.

    rec = reconcile_statement(session, stmt.id, auto_match=True)

    assert rec.status.value == "pending"
    assert rec.bank_debit_transaction_id is None


def test_ambiguous_bank_payment_not_silently_chosen(session, checking_account, credit_card_account):
    imp = _make_import(session, credit_card_account.id)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 2, -10000)
    stmt = _make_statement(session, credit_card_account.id, imp.id, total_minor=10000)

    # Two equally-plausible bank debits: same amount, same date -> a genuine tie.
    _add_bank_debit(session, checking_account.id, 15, -10000, description="Card Payment A")
    _add_bank_debit(session, checking_account.id, 15, -10000, description="Card Payment B")

    rec = reconcile_statement(session, stmt.id, auto_match=True)

    assert rec.status.value == "pending"  # not silently mismatched or reconciled
    assert rec.bank_debit_transaction_id is None

    from app.reconciliation.engine import get_ambiguous_candidates
    candidates = get_ambiguous_candidates(session, stmt)
    assert len(candidates) == 2
    assert {c.normalized_description for c in candidates} == {"Card Payment A", "Card Payment B"}


def test_manual_selection_resolves_ambiguity(session, checking_account, credit_card_account):
    imp = _make_import(session, credit_card_account.id)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 2, -10000)
    stmt = _make_statement(session, credit_card_account.id, imp.id, total_minor=10000)

    tx_a = _add_bank_debit(session, checking_account.id, 15, -10000, description="Card Payment A")
    _add_bank_debit(session, checking_account.id, 15, -10000, description="Card Payment B")

    # Auto-reconcile first — stays ambiguous/pending.
    reconcile_statement(session, stmt.id, auto_match=True)

    # User explicitly picks one.
    rec = reconcile_statement(session, stmt.id, bank_debit_transaction_id=tx_a.id)

    assert rec.status.value == "reconciled"
    assert rec.bank_debit_transaction_id == tx_a.id


def test_clear_best_candidate_not_treated_as_ambiguous(session, checking_account, credit_card_account):
    """A close-but-not-tied second candidate should NOT block auto-matching —
    only a genuine tie should."""
    imp = _make_import(session, credit_card_account.id)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 2, -10000)
    stmt = _make_statement(session, credit_card_account.id, imp.id, total_minor=10000)

    exact_match = _add_bank_debit(session, checking_account.id, 15, -10000, description="Exact")
    _add_bank_debit(session, checking_account.id, 10, -9500, description="Different amount, different date")

    rec = reconcile_statement(session, stmt.id, auto_match=True)

    assert rec.status.value == "reconciled"
    assert rec.bank_debit_transaction_id == exact_match.id


def test_manual_resolution_persists_and_does_not_overwrite_computed_numbers(session, checking_account, credit_card_account):
    imp = _make_import(session, credit_card_account.id)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 2, -10000)
    stmt = _make_statement(session, credit_card_account.id, imp.id, total_minor=15000)
    _add_bank_debit(session, checking_account.id, 15, -15000)

    rec = reconcile_statement(session, stmt.id, auto_match=True)
    assert rec.resolved_by_user is False

    resolved = resolve_reconciliation(
        session, rec.id, notes="Confirmed with issuer: missing gym membership charge.",
        tags=["missing_transaction"],
    )

    assert resolved.resolved_by_user is True
    assert resolved.resolution_notes.startswith("Confirmed")
    assert resolved.transaction_total_minor == rec.transaction_total_minor  # untouched
    assert resolved.diff_transactions_vs_statement_minor == rec.diff_transactions_vs_statement_minor


def test_an_ordinary_purchase_near_the_amount_is_not_suggested(session, checking_account, credit_card_account):
    """A small bill: a purchase a few euros off is no payment; a card-bill debit
    at the same distance (a partial or fee-reduced payment) still is."""
    from app.reconciliation.engine import find_candidate_bank_debits

    imp = _make_import(session, credit_card_account.id)
    _add_cc_transaction(session, credit_card_account.id, imp.id, 2, -1500)
    stmt = _make_statement(session, credit_card_account.id, imp.id, total_minor=1500)

    _add_bank_debit(session, checking_account.id, 12, -1150, description="Bakery Sonnenschein")
    bill = _add_bank_debit(session, checking_account.id, 14, -1200, description="Card settlement")
    bill.category = "Card bills"
    session.add(bill)
    session.commit()

    found = [tx.id for tx, _ in find_candidate_bank_debits(session, stmt)]
    assert found == [bill.id]
