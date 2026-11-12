"""Tests for checking<->savings (and generally any non-credit-card account
pair) transfer detection now running automatically as part of the import
pipeline — verified through the real API, not the pure function directly
(that's covered separately in test_transfers.py).
"""
from __future__ import annotations

import io

from tests.pdf_fixtures import write_text_pdf


def _import_pdf(client, tmp_path, name, lines, account_id):
    path = write_text_pdf(tmp_path / name, lines)
    with open(path, "rb") as f:
        files = {"file": (name, f, "application/pdf")}
        preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id})
    assert preview.status_code == 200, preview.text
    p = preview.json()
    commit = client.post("/api/imports/commit", json={"staging_id": p["staging_id"], "account_id": account_id})
    assert commit.status_code == 200, commit.text
    return commit.json()


def _get_statement_id(client, cc_account_id):
    r = client.get(f"/api/credit-cards/{cc_account_id}/statements")
    assert r.status_code == 200
    return r.json()[0]["id"]


def _create_account(client, name, account_type, currency="EUR"):
    r = client.post("/api/accounts", json={"name": name, "account_type": account_type, "currency": currency})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _import_csv(client, filename, content: bytes, account_id: int):
    files = {"file": (filename, io.BytesIO(content), "text/csv")}
    preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id})
    assert preview.status_code == 200, preview.text
    p = preview.json()
    commit = client.post("/api/imports/commit", json={"staging_id": p["staging_id"], "account_id": account_id})
    assert commit.status_code == 200, commit.text
    return commit.json()


def _tx_by_description(client, description):
    items = client.get("/api/transactions", params={"page_size": 500}).json()["items"]
    matches = [t for t in items if t["normalized_description"] == description]
    assert len(matches) == 1, f"expected exactly one match for {description!r}, got {matches}"
    return matches[0]


# ---------------------------------------------------------------------------

def test_checking_to_savings_transfer_detected(client):
    checking_id = _create_account(client, "Checking", "checking")
    savings_id = _create_account(client, "Savings", "savings")

    _import_csv(client, "checking.csv", b"Date,Description,Amount\n2026-03-15,Transfer to Savings,-500.00\n", checking_id)
    _import_csv(client, "savings.csv", b"Date,Description,Amount\n2026-03-16,Transfer from Checking,500.00\n", savings_id)

    out_tx = _tx_by_description(client, "Transfer to Savings")
    in_tx = _tx_by_description(client, "Transfer from Checking")

    assert out_tx["is_transfer"] is True
    assert out_tx["transaction_type"] == "transfer"
    assert in_tx["is_transfer"] is True
    assert in_tx["transaction_type"] == "transfer"


def test_savings_to_checking_transfer_detected(client):
    checking_id = _create_account(client, "Checking", "checking")
    savings_id = _create_account(client, "Savings", "savings")

    _import_csv(client, "savings.csv", b"Date,Description,Amount\n2026-04-01,Withdraw to Checking,-200.00\n", savings_id)
    _import_csv(client, "checking.csv", b"Date,Description,Amount\n2026-04-02,Deposit from Savings,200.00\n", checking_id)

    out_tx = _tx_by_description(client, "Withdraw to Checking")
    in_tx = _tx_by_description(client, "Deposit from Savings")
    assert out_tx["is_transfer"] is True
    assert in_tx["is_transfer"] is True


def test_small_difference_not_treated_as_transfer_without_iban(client):
    checking_id = _create_account(client, "Checking", "checking")
    savings_id = _create_account(client, "Savings", "savings")

    _import_csv(client, "checking.csv", b"Date,Description,Amount\n2026-03-15,Send to Savings,-500.00\n", checking_id)
    _import_csv(client, "savings.csv", b"Date,Description,Amount\n2026-03-16,Receive from Checking,499.50\n", savings_id)

    assert _tx_by_description(client, "Send to Savings")["is_transfer"] is False
    assert _tx_by_description(client, "Receive from Checking")["is_transfer"] is False


def test_a_difference_keeps_both_sides_counted_even_between_own_accounts(client):
    """500.00 sent, 499.50 arrived: paired, the 0.50 fee would vanish from the totals."""
    checking_id = _create_account(client, "Checking", "checking")
    savings_id = _create_account(client, "Savings", "savings")
    r = client.patch(f"/api/accounts/{savings_id}", json={"iban": "DE02 1203 0000 0000 2020 51"})
    assert r.status_code == 200, r.text

    _import_csv(
        client, "checking.csv",
        b"Date,Description,IBAN,Amount\n2026-03-15,Send to Savings,DE02120300000000202051,-500.00\n",
        checking_id,
    )
    _import_csv(client, "savings.csv", b"Date,Description,Amount\n2026-03-16,Receive from Checking,499.50\n", savings_id)

    assert _tx_by_description(client, "Send to Savings")["is_transfer"] is False
    assert _tx_by_description(client, "Receive from Checking")["is_transfer"] is False
    totals = client.get("/api/analytics/totals").json()
    assert totals["net_minor"] == -50


def test_date_window_matching(client):
    checking_id = _create_account(client, "Checking", "checking")
    savings_id = _create_account(client, "Savings", "savings")

    # 3 days apart -> within the default window, should match.
    _import_csv(client, "checking.csv", b"Date,Description,Amount\n2026-05-01,Move Out,-300.00\n", checking_id)
    _import_csv(client, "savings.csv", b"Date,Description,Amount\n2026-05-04,Move In,300.00\n", savings_id)

    out_tx = _tx_by_description(client, "Move Out")
    in_tx = _tx_by_description(client, "Move In")
    assert out_tx["is_transfer"] is True
    assert in_tx["is_transfer"] is True


def test_date_gap_too_large_not_matched(client):
    checking_id = _create_account(client, "Checking", "checking")
    savings_id = _create_account(client, "Savings", "savings")

    _import_csv(client, "checking.csv", b"Date,Description,Amount\n2026-05-01,Move Out Far,-300.00\n", checking_id)
    _import_csv(client, "savings.csv", b"Date,Description,Amount\n2026-05-20,Move In Far,300.00\n", savings_id)

    out_tx = _tx_by_description(client, "Move Out Far")
    in_tx = _tx_by_description(client, "Move In Far")
    assert out_tx["is_transfer"] is False
    assert out_tx["transaction_type"] == "expense"
    assert in_tx["is_transfer"] is False
    assert in_tx["transaction_type"] == "income"


def test_similar_ordinary_transactions_not_classified_as_transfers(client):
    """Coincidentally equal amounts that are NOT actually a transfer (an
    unrelated bill payment and an unrelated refund) must stay as ordinary
    income/expense — the amount+date coincidence alone must still only
    match when there genuinely is exactly one plausible counterpart. Here
    we make it unambiguous the other direction: put them far enough apart
    in amount that they simply don't qualify."""
    checking_id = _create_account(client, "Checking", "checking")
    savings_id = _create_account(client, "Savings", "savings")

    _import_csv(client, "checking.csv", b"Date,Description,Amount\n2026-06-01,Electric Bill,-84.32\n", checking_id)
    _import_csv(client, "savings.csv", b"Date,Description,Amount\n2026-06-02,Interest Payment,12.10\n", savings_id)

    bill = _tx_by_description(client, "Electric Bill")
    interest = _tx_by_description(client, "Interest Payment")
    assert bill["is_transfer"] is False
    assert bill["transaction_type"] == "expense"
    assert interest["is_transfer"] is False
    assert interest["transaction_type"] == "income"


def test_ambiguous_candidates_not_silently_classified(client):
    checking_id = _create_account(client, "Checking", "checking")
    savings_id = _create_account(client, "Savings", "savings")
    other_savings_id = _create_account(client, "Second Savings", "savings")

    # Import BOTH competing counterparts before the transaction that would
    # need to choose between them, so the tie genuinely exists at the
    # moment detection runs (importing them after the fact would let the
    # first one match unambiguously before the second one even existed).
    _import_csv(client, "savings.csv", b"Date,Description,Amount\n2026-07-01,Ambiguous In A,400.00\n", savings_id)
    _import_csv(client, "savings2.csv", b"Date,Description,Amount\n2026-07-01,Ambiguous In B,400.00\n", other_savings_id)
    _import_csv(client, "checking.csv", b"Date,Description,Amount\n2026-07-01,Ambiguous Out,-400.00\n", checking_id)

    out_tx = _tx_by_description(client, "Ambiguous Out")
    in_a = _tx_by_description(client, "Ambiguous In A")
    in_b = _tx_by_description(client, "Ambiguous In B")

    # Two equally plausible counterparts -> none auto-matched; all remain
    # visible as ordinary transactions rather than being silently paired.
    assert out_tx["is_transfer"] is False
    assert in_a["is_transfer"] is False
    assert in_b["is_transfer"] is False


def test_manual_correction_survives_recomputation(client):
    checking_id = _create_account(client, "Checking", "checking")
    savings_id = _create_account(client, "Savings", "savings")

    _import_csv(client, "checking.csv", b"Date,Description,Amount\n2026-08-01,Suspicious Match,-150.00\n", checking_id)
    _import_csv(client, "savings.csv", b"Date,Description,Amount\n2026-08-02,Coincidence,150.00\n", savings_id)

    # These would normally auto-match — confirm that first.
    auto = _tx_by_description(client, "Suspicious Match")
    assert auto["is_transfer"] is True

    # User manually corrects it back to a regular expense (e.g. they know
    # it's actually an unrelated cash withdrawal, not a transfer).
    r = client.patch(f"/api/transactions/{auto['id']}", json={"transaction_type": "expense"})
    assert r.status_code == 200
    assert r.json()["transaction_type"] == "expense"

    # A further import (triggering another detection pass) must not
    # revert the user's manual correction.
    _import_csv(client, "unrelated.csv", b"Date,Description,Amount\n2026-08-10,Unrelated,-5.00\n", checking_id)

    still_corrected = _tx_by_description(client, "Suspicious Match")
    assert still_corrected["transaction_type"] == "expense"


def test_reimporting_is_idempotent_no_duplicate_pairs(client):
    checking_id = _create_account(client, "Checking", "checking")
    savings_id = _create_account(client, "Savings", "savings")

    _import_csv(client, "checking.csv", b"Date,Description,Amount\n2026-09-01,Idempotent Out,-250.00\n", checking_id)
    _import_csv(client, "savings.csv", b"Date,Description,Amount\n2026-09-02,Idempotent In,250.00\n", savings_id)

    out_tx = _tx_by_description(client, "Idempotent Out")
    assert out_tx["is_transfer"] is True

    # Trigger another detection pass (via a new, unrelated import) and
    # confirm the pair is still exactly one pair — not re-paired, not
    # duplicated, counts unchanged.
    total_before = client.get("/api/transactions").json()["total"]
    _import_csv(client, "unrelated2.csv", b"Date,Description,Amount\n2026-09-15,Another Item,-3.00\n", checking_id)
    total_after = client.get("/api/transactions").json()["total"]
    assert total_after == total_before + 1  # only the new unrelated transaction added

    out_tx_again = _tx_by_description(client, "Idempotent Out")
    assert out_tx_again["is_transfer"] is True


def test_transfer_detection_persists_across_restart(tmp_path):
    """Same multi-session guarantee as CSV/XLSX/PDF imports (spec section
    41): a detected transfer pair must survive a full application
    restart, not just live within one process's session."""
    from sqlmodel import Session, SQLModel, create_engine, select

    from app.db.models import Account, AccountType, Transaction
    from app.services.import_reading import parse_file
    from app.services.import_service import commit_parsed_import
    from tests.pdf_fixtures import write_text_pdf  # noqa: F401 (not used, keeps import style consistent)

    db_path = tmp_path / "finance.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    checking_csv = tmp_path / "checking.csv"
    checking_csv.write_text("Date,Description,Amount\n2026-10-01,Restart Transfer Out,-750.00\n")
    savings_csv = tmp_path / "savings.csv"
    savings_csv.write_text("Date,Description,Amount\n2026-10-02,Restart Transfer In,750.00\n")

    # Session 1: create accounts, import both legs.
    with Session(engine) as s:
        checking = Account(name="Checking", account_type=AccountType.CHECKING, currency="EUR")
        savings = Account(name="Savings", account_type=AccountType.SAVINGS, currency="EUR")
        s.add(checking)
        s.add(savings)
        s.commit()
        s.refresh(checking)
        s.refresh(savings)

        commit_parsed_import(s, parse_file(checking_csv), checking.id, "imports/checking.csv")
        commit_parsed_import(s, parse_file(savings_csv), savings.id, "imports/savings.csv")

        tx = s.exec(select(Transaction).where(Transaction.normalized_description == "Restart Transfer Out")).one()
        assert tx.is_transfer is True

    # "Restart": brand-new engine/session against the same file.
    engine2 = create_engine(f"sqlite:///{db_path}")
    with Session(engine2) as s:
        out_tx = s.exec(select(Transaction).where(Transaction.normalized_description == "Restart Transfer Out")).one()
        in_tx = s.exec(select(Transaction).where(Transaction.normalized_description == "Restart Transfer In")).one()
        assert out_tx.is_transfer is True
        assert in_tx.is_transfer is True
        assert out_tx.transfer_pair_id == in_tx.id
        assert in_tx.transfer_pair_id == out_tx.id


def test_no_double_counting_for_generic_transfers(client):
    checking_id = _create_account(client, "Checking", "checking")
    savings_id = _create_account(client, "Savings", "savings")

    _import_csv(
        client, "checking.csv",
        b"Date,Description,Amount\n"
        b"2026-03-01,Salary,2500.00\n"
        b"2026-03-15,Transfer to Savings,-500.00\n",
        checking_id,
    )
    _import_csv(client, "savings.csv", b"Date,Description,Amount\n2026-03-16,Transfer from Checking,500.00\n", savings_id)

    totals = client.get("/api/analytics/totals").json()
    # Only the salary counts as income; the transfer must not appear as an
    # expense on checking NOR as income on savings.
    assert totals["income_minor"] == 250000
    assert totals["expenses_minor"] == 0

    transfers = client.get("/api/analytics/transfers-summary").json()
    # One movement of 500.00 — not 1000.00 just because both legs are visible.
    assert transfers["total_transferred_minor"] == 50000
    assert transfers["transfer_count"] == 1


# ---------------------------------------------------------------------------
# Full re-scan: safe against import order (spec: never silently reassign,
# surface newly-ambiguous situations rather than keeping a stale match)
# ---------------------------------------------------------------------------

def test_rerun_reconsiders_previously_matched_pair_when_new_competitor_arrives(client):
    """The exact sequence requested: Import A gets auto-matched, Import B
    later creates a genuinely competing candidate, then an explicit
    re-run must reconsider — not silently keep the stale pair, and not
    silently reassign to a different partner either. Both possibilities
    become ambiguous and should be surfaced as such (left unmatched)."""
    checking_id = _create_account(client, "Checking", "checking")
    savings_id = _create_account(client, "Savings", "savings")
    other_savings_id = _create_account(client, "Second Savings", "savings")

    # Import A: X (-500 checking) and Y (+500 savings) -> unambiguous at
    # the time, so incremental detection pairs them immediately.
    _import_csv(client, "checking.csv", b"Date,Description,Amount\n2026-11-01,Reorder Out,-500.00\n", checking_id)
    _import_csv(client, "savings.csv", b"Date,Description,Amount\n2026-11-02,Reorder In Y,500.00\n", savings_id)

    x = _tx_by_description(client, "Reorder Out")
    y = _tx_by_description(client, "Reorder In Y")
    assert x["is_transfer"] is True
    assert y["is_transfer"] is True

    # Import B, later: Z arrives on a different savings account, equally
    # plausible as X's counterpart — same amount, and the SAME date as Y,
    # so it's a genuine tie (not just "also somewhat close").
    _import_csv(client, "savings2.csv", b"Date,Description,Amount\n2026-11-02,Reorder In Z,500.00\n", other_savings_id)
    z = _tx_by_description(client, "Reorder In Z")
    # Incremental detection alone must not touch the already-matched pair —
    # confirms incremental mode never re-evaluates existing matches.
    assert z["is_transfer"] is False
    x_unchanged = _tx_by_description(client, "Reorder Out")
    assert x_unchanged["is_transfer"] is True

    # Explicit re-run: now genuinely reconsiders X, Y, and Z together.
    r = client.post("/api/transfers/rerun-detection")
    assert r.status_code == 200
    stats = r.json()
    assert stats["transactions_reverted_to_ordinary"] == 2  # X and Y unpaired for reconsideration
    assert stats["pairs_matched"] == 0  # X now has two equally-good candidates -> ambiguous

    x_after = _tx_by_description(client, "Reorder Out")
    y_after = _tx_by_description(client, "Reorder In Y")
    z_after = _tx_by_description(client, "Reorder In Z")

    # No silent reassignment to Z, and no silently keeping the old match
    # with Y either — the ambiguity is surfaced by leaving all three as
    # ordinary, visible transactions.
    assert x_after["is_transfer"] is False
    assert x_after["transaction_type"] == "expense"
    assert y_after["is_transfer"] is False
    assert y_after["transaction_type"] == "income"
    assert z_after["is_transfer"] is False
    assert z_after["transaction_type"] == "income"


def test_rerun_still_matches_unambiguous_pairs_correctly(client):
    """A re-run isn't just a "clear everything" operation — genuinely
    unambiguous pairs must still be (re-)detected correctly."""
    checking_id = _create_account(client, "Checking", "checking")
    savings_id = _create_account(client, "Savings", "savings")

    _import_csv(client, "checking.csv", b"Date,Description,Amount\n2026-11-10,Clean Out,-300.00\n", checking_id)
    _import_csv(client, "savings.csv", b"Date,Description,Amount\n2026-11-11,Clean In,300.00\n", savings_id)

    before = _tx_by_description(client, "Clean Out")
    assert before["is_transfer"] is True

    r = client.post("/api/transfers/rerun-detection")
    assert r.status_code == 200
    stats = r.json()
    assert stats["pairs_matched"] == 1

    after = _tx_by_description(client, "Clean Out")
    assert after["is_transfer"] is True


def test_rerun_never_touches_manually_corrected_transaction(client):
    checking_id = _create_account(client, "Checking", "checking")
    savings_id = _create_account(client, "Savings", "savings")

    _import_csv(client, "checking.csv", b"Date,Description,Amount\n2026-11-15,Manual Case,-220.00\n", checking_id)
    _import_csv(client, "savings.csv", b"Date,Description,Amount\n2026-11-16,Manual Case Match,220.00\n", savings_id)

    auto = _tx_by_description(client, "Manual Case")
    assert auto["is_transfer"] is True

    # User overrides it back to an ordinary expense.
    client.patch(f"/api/transactions/{auto['id']}", json={"transaction_type": "expense"})

    r = client.post("/api/transfers/rerun-detection")
    assert r.status_code == 200

    still_expense = _tx_by_description(client, "Manual Case")
    assert still_expense["transaction_type"] == "expense"
    assert still_expense["is_transfer"] is False

    # Its former counterpart, now unpaired by the manual override, is
    # reconsidered on its own (no other candidate) -> stays ordinary income,
    # not left dangling as a "transfer" with a partner that no longer is one.
    counterpart = _tx_by_description(client, "Manual Case Match")
    assert counterpart["is_transfer"] is False
    assert counterpart["transaction_type"] == "income"


def test_rerun_never_touches_credit_card_reconciliation_transfers(client, tmp_path):
    """Re-running generic transfer detection must leave the credit-card
    reconciliation engine's own transfer marking completely alone."""
    checking_id = _create_account(client, "Checking", "checking")
    cc_id = _create_account(client, "VISA", "credit_card")

    _import_pdf(client, tmp_path, "cc.pdf", [
        "Credit Card Statement", "VISA ending 1234",
        "Statement Period: 01.03.2026 - 10.03.2026",
        "02.03.2026 Amazon.de 100.00 EUR",
        "Statement Total: 100.00 EUR",
    ], cc_id)
    stmt_id = _get_statement_id(client, cc_id)
    _import_csv(client, "bank.csv", b"Date,Description,Amount\n2026-03-12,Credit Card Payment,-100.00\n", checking_id)
    client.get(f"/api/reconciliation/statements/{stmt_id}")  # triggers reconciliation + transfer marking

    payment_before = _tx_by_description(client, "Credit Card Payment")
    assert payment_before["is_transfer"] is True

    r = client.post("/api/transfers/rerun-detection")
    assert r.status_code == 200
    stats = r.json()
    assert stats["transactions_reverted_to_ordinary"] == 0  # CC-reconciliation transfer untouched

    payment_after = _tx_by_description(client, "Credit Card Payment")
    assert payment_after["is_transfer"] is True
    assert payment_after["transaction_type"] == "transfer"

    recon_after = client.get(f"/api/reconciliation/statements/{stmt_id}").json()
    assert recon_after["status"] == "reconciled"


def test_rerun_is_idempotent_no_duplicate_pairs(client):
    checking_id = _create_account(client, "Checking", "checking")
    savings_id = _create_account(client, "Savings", "savings")

    _import_csv(client, "checking.csv", b"Date,Description,Amount\n2026-11-20,Idempotent Rerun Out,-175.00\n", checking_id)
    _import_csv(client, "savings.csv", b"Date,Description,Amount\n2026-11-21,Idempotent Rerun In,175.00\n", savings_id)

    total_before = client.get("/api/transactions").json()["total"]

    r1 = client.post("/api/transfers/rerun-detection").json()
    r2 = client.post("/api/transfers/rerun-detection").json()
    r3 = client.post("/api/transfers/rerun-detection").json()

    total_after = client.get("/api/transactions").json()["total"]
    assert total_after == total_before  # no new/duplicate transactions ever created

    # Every re-run reaches the exact same stable result.
    assert r1["pairs_matched"] == r2["pairs_matched"] == r3["pairs_matched"] == 1

    out_tx = _tx_by_description(client, "Idempotent Rerun Out")
    in_tx = _tx_by_description(client, "Idempotent Rerun In")
    assert out_tx["is_transfer"] is True
    assert in_tx["is_transfer"] is True
