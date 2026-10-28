from __future__ import annotations

import io


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


def _write_pdf(tmp_path, name, lines):
    from tests.pdf_fixtures import write_text_pdf
    return write_text_pdf(tmp_path / name, lines)


def _import_pdf(client, path, account_id):
    with open(path, "rb") as f:
        files = {"file": (path.name, f, "application/pdf")}
        preview = client.post("/api/imports/preview", files=files, data={"account_id": account_id})
    assert preview.status_code == 200, preview.text
    p = preview.json()
    commit = client.post("/api/imports/commit", json={"staging_id": p["staging_id"], "account_id": account_id})
    assert commit.status_code == 200, commit.text
    return commit.json()


def test_list_credit_cards_empty(client):
    r = client.get("/api/credit-cards")
    assert r.status_code == 200
    assert r.json() == []


def test_credit_card_summary_with_statement(client, tmp_path):
    _create_account(client, "Checking", "checking")
    cc_id = _create_account(client, "VISA", "credit_card")

    cc_pdf = _write_pdf(tmp_path, "cc_march.pdf", [
        "Credit Card Statement",
        "VISA ending 1234",
        "Statement Period: 01.03.2026 - 10.03.2026",
        "02.03.2026 Amazon.de 100.00 EUR",
        "Statement Total: 100.00 EUR",
    ])
    _import_pdf(client, cc_pdf, cc_id)

    r = client.get("/api/credit-cards")
    assert r.status_code == 200
    summaries = r.json()
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["account"]["id"] == cc_id
    assert summary["statement_count"] == 1
    assert summary["latest_statement"]["statement_total_minor"] == 10000
    assert summary["latest_statement"]["transaction_count"] == 1
    # No matching bank payment imported yet -> pending, not mismatch.
    assert summary["latest_statement"]["reconciliation_status"] == "pending"


def test_statement_list_reflects_reconciliation_after_bank_payment_imported(client, tmp_path):
    checking_id = _create_account(client, "Checking", "checking")
    cc_id = _create_account(client, "VISA", "credit_card")

    cc_pdf = _write_pdf(tmp_path, "cc_march.pdf", [
        "Credit Card Statement",
        "VISA ending 1234",
        "Statement Period: 01.03.2026 - 10.03.2026",
        "02.03.2026 Amazon.de 100.00 EUR",
        "Statement Total: 100.00 EUR",
    ])
    _import_pdf(client, cc_pdf, cc_id)

    r = client.get(f"/api/credit-cards/{cc_id}/statements")
    assert r.status_code == 200
    assert r.json()[0]["reconciliation_status"] == "pending"

    # Now the matching bank debit arrives.
    bank_csv = b"Date,Description,Amount\n2026-03-12,Credit Card Payment,-100.00\n"
    _import_csv(client, "checking_march.csv", bank_csv, checking_id)

    r = client.get(f"/api/credit-cards/{cc_id}/statements")
    assert r.status_code == 200
    statement = r.json()[0]
    assert statement["reconciliation_status"] == "reconciled"
    assert statement["difference_minor"] == 0


def test_unknown_credit_card_account_returns_404(client):
    r = client.get("/api/credit-cards/9999/statements")
    assert r.status_code == 404


def test_non_credit_card_account_rejected_for_statements(client):
    checking_id = _create_account(client, "Checking", "checking")
    r = client.get(f"/api/credit-cards/{checking_id}/statements")
    assert r.status_code == 404
