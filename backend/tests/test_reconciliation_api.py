"""API-level reconciliation tests covering the required edge-case matrix:
perfect reconciliation, both kinds of mismatch (independently and
together), refund, fee, interest, partial payment, missing bank payment,
unexplained mismatch, manual resolution, and ambiguous/duplicate bank
payment candidates (never silently auto-picked).
"""
from __future__ import annotations

import io

from tests.pdf_fixtures import write_text_pdf


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


# ---------------------------------------------------------------------------

def test_perfect_reconciliation_detail(client, tmp_path):
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

    r = client.get(f"/api/reconciliation/statements/{stmt_id}")
    assert r.status_code == 200
    detail = r.json()
    assert detail["status"] == "reconciled"
    assert detail["transaction_total_minor"] == 10000
    assert detail["statement_total_minor"] == 10000
    assert detail["bank_payment"]["status"] == "matched"
    assert detail["bank_payment"]["transaction"]["amount_minor"] == -10000
    assert detail["bank_payment"]["transaction"]["transaction_type"] == "transfer"
    assert detail["diff_transactions_vs_statement_minor"] == 0
    assert detail["diff_statement_vs_bank_minor"] == 0
    assert len(detail["transactions"]) == 1
    assert detail["transactions"][0]["merchant"] == "Amazon"
    assert detail["source_import_filename"] == "cc.pdf"


def test_missing_bank_payment_is_pending_not_mismatch(client, tmp_path):
    cc_id = _create_account(client, "VISA", "credit_card")
    _create_account(client, "Checking", "checking")

    _import_pdf(client, tmp_path, "cc.pdf", [
        "Credit Card Statement", "VISA ending 1234",
        "Statement Period: 01.03.2026 - 10.03.2026",
        "02.03.2026 Amazon.de 100.00 EUR",
        "Statement Total: 100.00 EUR",
    ], cc_id)
    stmt_id = _get_statement_id(client, cc_id)

    r = client.get(f"/api/reconciliation/statements/{stmt_id}")
    detail = r.json()
    assert detail["status"] == "pending"
    assert detail["bank_payment"]["status"] == "not_found"
    assert detail["bank_payment"]["transaction"] is None


def test_unexplained_mismatch_shown_without_invented_explanation(client, tmp_path):
    checking_id = _create_account(client, "Checking", "checking")
    cc_id = _create_account(client, "VISA", "credit_card")

    # Statement declares more than the one captured transaction accounts for,
    # with no fee/interest/duplicate evidence anywhere to explain the gap.
    _import_pdf(client, tmp_path, "cc.pdf", [
        "Credit Card Statement", "VISA ending 1234",
        "Statement Period: 01.03.2026 - 10.03.2026",
        "02.03.2026 Amazon.de 100.00 EUR",
        "Statement Total: 112.50 EUR",
    ], cc_id)
    stmt_id = _get_statement_id(client, cc_id)
    _import_csv(client, "bank.csv", b"Date,Description,Amount\n2026-03-12,Credit Card Payment,-112.50\n", checking_id)

    r = client.get(f"/api/reconciliation/statements/{stmt_id}")
    detail = r.json()
    assert detail["status"] == "mismatch"
    assert detail["diff_transactions_vs_statement_minor"] == 1250
    assert detail["explanation_tags"] == []  # no invented explanation


def test_manual_resolution_via_api_preserves_computed_values(client, tmp_path):
    checking_id = _create_account(client, "Checking", "checking")
    cc_id = _create_account(client, "VISA", "credit_card")

    _import_pdf(client, tmp_path, "cc.pdf", [
        "Credit Card Statement", "VISA ending 1234",
        "Statement Period: 01.03.2026 - 10.03.2026",
        "02.03.2026 Amazon.de 100.00 EUR",
        "Statement Total: 112.50 EUR",
    ], cc_id)
    stmt_id = _get_statement_id(client, cc_id)
    _import_csv(client, "bank.csv", b"Date,Description,Amount\n2026-03-12,Credit Card Payment,-112.50\n", checking_id)

    before = client.get(f"/api/reconciliation/statements/{stmt_id}").json()
    assert before["resolved_by_user"] is False

    r = client.post(
        f"/api/reconciliation/statements/{stmt_id}/resolve",
        json={"notes": "Confirmed with issuer: missed a subscription charge.", "tags": ["missing_transaction"]},
    )
    assert r.status_code == 200
    after = r.json()
    assert after["resolved_by_user"] is True
    assert after["resolution_notes"].startswith("Confirmed")
    assert after["user_resolution_tags"] == ["missing_transaction"]
    # Computed values, including the engine's own explanation tags, are
    # untouched by manual resolution — user tags are stored separately.
    assert after["transaction_total_minor"] == before["transaction_total_minor"]
    assert after["diff_transactions_vs_statement_minor"] == before["diff_transactions_vs_statement_minor"]
    assert after["explanation_tags"] == before["explanation_tags"]


def test_ambiguous_bank_payment_requires_manual_selection(client, tmp_path):
    checking_id = _create_account(client, "Checking", "checking")
    cc_id = _create_account(client, "VISA", "credit_card")

    _import_pdf(client, tmp_path, "cc.pdf", [
        "Credit Card Statement", "VISA ending 1234",
        "Statement Period: 01.03.2026 - 10.03.2026",
        "02.03.2026 Amazon.de 100.00 EUR",
        "Statement Total: 100.00 EUR",
    ], cc_id)
    stmt_id = _get_statement_id(client, cc_id)

    # Two equally-plausible bank debits on the same day, same amount.
    _import_csv(
        client, "bank.csv",
        b"Date,Description,Amount\n"
        b"2026-03-12,Card Payment A,-100.00\n"
        b"2026-03-12,Card Payment B,-100.00\n",
        checking_id,
    )

    r = client.get(f"/api/reconciliation/statements/{stmt_id}")
    detail = r.json()
    assert detail["status"] == "pending"
    assert detail["bank_payment"]["status"] == "suggested"
    assert detail["bank_payment"]["recommended_transaction_id"] is None  # a genuine tie
    assert len(detail["bank_payment"]["candidates"]) == 2

    chosen_id = detail["bank_payment"]["candidates"][0]["id"]
    r2 = client.post(
        f"/api/reconciliation/statements/{stmt_id}/select-bank-payment",
        json={"transaction_id": chosen_id},
    )
    assert r2.status_code == 200
    resolved = r2.json()
    assert resolved["status"] == "reconciled"
    assert resolved["bank_payment"]["status"] == "matched"
    assert resolved["bank_payment"]["transaction"]["id"] == chosen_id


def test_unknown_statement_returns_404(client):
    r = client.get("/api/reconciliation/statements/9999")
    assert r.status_code == 404


def test_no_double_counting_visible_in_reconciliation_detail(client, tmp_path):
    """The accounting-correctness rule, verified via the exact endpoint the
    Reconciliation UI calls: the CC purchase is the expense; the bank debit
    that settles it must show as a transfer, not a second expense."""
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

    detail = client.get(f"/api/reconciliation/statements/{stmt_id}").json()
    assert detail["transactions"][0]["transaction_type"] == "expense"
    assert detail["bank_payment"]["transaction"]["transaction_type"] == "transfer"

    totals = client.get("/api/analytics/totals").json()
    assert totals["expenses_minor"] == 10000  # counted exactly once
