"""Regression tests for the import workflow: preview/commit consistency,
staging safety, stored documents and PDF layout detection."""
from __future__ import annotations

import io

from app.db.models import DocumentType
from app.importers.pdf_importer import PDFImporter
from tests.pdf_fixtures import write_text_pdf


def _create_account(client, name="Checking", account_type="checking"):
    r = client.post("/api/accounts", json={"name": name, "account_type": account_type})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _preview(client, name, content: bytes, account_id: int):
    r = client.post("/api/imports/preview", files={"file": (name, io.BytesIO(content), "text/csv")},
                    data={"account_id": account_id})
    assert r.status_code == 200, r.text
    return r.json()


def _commit(client, preview, account_id, decisions=()):
    return client.post("/api/imports/commit", json={
        "staging_id": preview["staging_id"], "account_id": account_id,
        "row_decisions": [{"source_row_index": i, "decision": d} for i, d in decisions],
    })


def test_identical_rows_in_one_file_are_all_imported(client):
    """Two 3.50 tickets on the same day are two real purchases. The preview
    said "new, new" and the commit used to silently drop one of them."""
    account_id = _create_account(client)
    csv = b"Date,Description,Amount\n2026-02-01,BVG Ticket,-3.50\n2026-02-01,BVG Ticket,-3.50\n"
    preview = _preview(client, "a.csv", csv, account_id)
    assert [c["status"] for c in preview["row_classifications"]] == ["new", "new"]
    assert preview["row_classifications"][1]["repeated_in_file"] is True

    commit = _commit(client, preview, account_id)
    assert commit.status_code == 200, commit.text
    assert commit.json()["transactions_created"] == 2


def test_overlapping_file_counts_duplicates_as_multiset(client):
    account_id = _create_account(client)
    _commit(client, _preview(client, "a.csv", b"Date,Description,Amount\n2026-02-01,BVG Ticket,-3.50\n", account_id),
            account_id)

    # The overlapping export contains the ticket twice: one is the known
    # one (skipped by default); the second is shown for review but kept by
    # default — it is never silently dropped.
    csv = b"Date,Description,Amount\n2026-02-01,BVG Ticket,-3.50\n2026-02-01,BVG Ticket,-3.50\n2026-02-02,Kino,-9.00\n"
    preview = _preview(client, "b.csv", csv, account_id)
    assert [c["status"] for c in preview["row_classifications"]] == ["exact_duplicate", "possible_duplicate", "new"]
    assert _commit(client, preview, account_id).json()["transactions_created"] == 2


def test_staging_id_cannot_address_arbitrary_files(client):
    for bad in ("../../etc/passwd", "*", "0" * 31 + "*"):
        r = client.post("/api/imports/commit", json={"staging_id": bad, "account_id": 1})
        assert r.status_code == 422, bad


def test_commit_twice_is_rejected(client):
    account_id = _create_account(client)
    preview = _preview(client, "a.csv", b"Date,Description,Amount\n2026-02-01,X,-1.00\n", account_id)
    assert _commit(client, preview, account_id).status_code == 200
    assert _commit(client, preview, account_id).status_code == 404  # staged file consumed


def test_discarding_a_preview_deletes_the_upload(client):
    from app.config import settings

    account_id = _create_account(client)
    preview = _preview(client, "a.csv", b"Date,Description,Amount\n2026-02-01,X,-1.00\n", account_id)
    assert list(settings.staging_dir.glob(f"{preview['staging_id']}*"))
    assert client.delete(f"/api/imports/staging/{preview['staging_id']}").status_code == 204
    assert not list(settings.staging_dir.glob(f"{preview['staging_id']}*"))


def test_removing_an_import_deletes_the_stored_document(client):
    from app.config import settings

    account_id = _create_account(client)
    preview = _preview(client, "statement.csv", b"Date,Description,Amount\n2026-02-01,X,-1.00\n", account_id)
    import_id = _commit(client, preview, account_id).json()["import_id"]
    assert len(list(settings.imports_dir.iterdir())) == 1

    assert client.delete(f"/api/imports/{import_id}").status_code == 200
    assert list(settings.imports_dir.iterdir()) == []


def test_reparse_with_manual_mapping(client):
    account_id = _create_account(client)
    preview = _preview(client, "a.csv", b"When;What;How much\n01.02.2026;Kino;-12,00\n", account_id)
    assert preview["ambiguous"] is True
    assert preview["available_columns"] == ["When", "What", "How much"]

    r = client.post(f"/api/imports/{preview['staging_id']}/reparse", json={
        "account_id": account_id,
        "options": {"column_mapping": {"date": "When", "description": "What", "amount": "How much"}},
    })
    assert r.status_code == 200, r.text
    reparsed = r.json()
    assert reparsed["ambiguous"] is False
    assert reparsed["new_count"] == 1

    # The commit uses the stored options, i.e. exactly what was previewed.
    commit = _commit(client, reparsed, account_id)
    assert commit.status_code == 200, commit.text
    assert commit.json()["transactions_created"] == 1


def test_parse_warnings_are_counted_in_preview(client):
    account_id = _create_account(client)
    preview = _preview(client, "a.csv", b"Date,Description,Amount\n2026-02-01,X,-1.00\n2026-02-02,Y,twelve\n", account_id)
    assert preview["unusable_row_count"] == 1
    assert preview["warning_count"] >= 1
    assert preview["new_count"] == 1


# --- PDF ---------------------------------------------------------------------

def test_bank_statement_mentioning_visa_stays_a_bank_statement(tmp_path):
    """Debit cards and the monthly card payment put "VISA" on ordinary bank
    statements; that used to flip every sign."""
    path = write_text_pdf(tmp_path / "bank.pdf", [
        "Kontoauszug", "Girokonto IBAN DE02 1203 0000 0000 2020 51",
        "Zeitraum: 01.03.2026 - 31.03.2026",
        "05.03.2026 Gehalt 2500,00 EUR",
        "10.03.2026 VISA Debitkarte REWE -45,67 EUR",
        "15.03.2026 Kreditkartenabrechnung VISA -312,40 EUR",
    ])
    result = PDFImporter(path).parse()
    assert result.document_type == DocumentType.BANK_STATEMENT
    assert [t.parsed_amount_minor for t in result.transactions] == [250000, -4567, -31240]


def test_balance_column_is_not_read_as_amount(tmp_path):
    path = write_text_pdf(tmp_path / "bank.pdf", [
        "Kontoauszug", "Zeitraum: 01.01.2026 - 31.01.2026",
        "15.01.2026 REWE -42,90 1.234,56",
        "16.01.2026 Gehalt 2.500,00 3.734,56",
    ])
    result = PDFImporter(path).parse()
    assert [t.parsed_amount_minor for t in result.transactions] == [-4290, 250000]


def test_trailing_minus_and_dates_without_year(tmp_path):
    path = write_text_pdf(tmp_path / "bank.pdf", [
        "Kontoauszug", "Zeitraum: 01.12.2025 - 31.01.2026",
        "30.12. 30.12. Miete 800,00-",
        "02.01. 02.01. Gutschrift 50,00+",
    ])
    result = PDFImporter(path).parse()
    assert [(t.parsed_date, t.parsed_amount_minor) for t in result.transactions] == [
        ("2025-12-30", -80000), ("2026-01-02", 5000),
    ]


def test_credit_card_statement_on_checking_account_is_refused(client, tmp_path):
    account_id = _create_account(client)
    path = write_text_pdf(tmp_path / "cc.pdf", [
        "Credit Card Statement", "Statement Period: 01.03.2026 - 10.03.2026",
        "02.03.2026 Amazon.de 100.00 EUR", "Statement Total: 100.00 EUR",
    ])
    with open(path, "rb") as f:
        r = client.post("/api/imports/preview", files={"file": ("cc.pdf", f, "application/pdf")},
                        data={"account_id": account_id})
    preview = r.json()
    assert preview["has_errors"] is True
    assert "credit-card statement" in preview["issues"][0]["message"]
    assert _commit(client, preview, account_id).status_code == 409


# ---------------------------------------------------------------------------
# Files a reader stumbles over, and imports that fail half-way
# ---------------------------------------------------------------------------

_CSV = b"Date,Description,Amount\n2026-02-01,X,-1.00\n"


def _staged_files():
    from app.config import settings

    return sorted(p.name for p in settings.staging_dir.iterdir())


def _stored_documents():
    from app.config import settings

    return sorted(p.name for p in settings.imports_dir.iterdir())


def test_a_spreadsheet_with_a_damaged_sheet_is_explained_not_a_crash(client, tmp_path):
    """The workbook opens (its list of sheets is fine); the sheet's rows are
    only read later — and end in the middle of a cell."""
    import zipfile

    from tests.xlsx_fixtures import write_xlsx

    intact = write_xlsx(tmp_path / "intact.xlsx", ["Date", "Description", "Amount"],
                        [["2026-02-01", f"Shop {i}", -1.5] for i in range(50)])
    damaged = io.BytesIO()
    with zipfile.ZipFile(intact) as src, zipfile.ZipFile(damaged, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info)
            dst.writestr(info, data[: len(data) // 2] if info.filename.startswith("xl/worksheets/") else data)

    account_id = _create_account(client)
    r = client.post("/api/imports/preview", data={"account_id": account_id}, files={"file": (
        "damaged.xlsx", io.BytesIO(damaged.getvalue()),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})

    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["has_errors"] is True and preview["transaction_count"] == 0
    assert "Could not open the spreadsheet" in preview["issues"][0]["message"]


def test_a_file_a_reader_stumbles_over_is_explained_and_not_kept(client, monkeypatch):
    from app.importers.csv_importer import CSVImporter

    def stumble(_self):
        raise KeyError("a column the reader took for granted")

    monkeypatch.setattr(CSVImporter, "parse", stumble)
    account_id = _create_account(client)

    for data in ({"account_id": account_id}, {}):  # with the account chosen, and to be recognized
        r = client.post("/api/imports/preview", files={"file": ("a.csv", io.BytesIO(_CSV), "text/csv")}, data=data)
        assert r.status_code == 422, r.text
        assert "could not be read" in r.json()["detail"] and "KeyError" in r.json()["detail"]
        # nobody knows its staging id: the uploaded statement must not lie around until the purge
        assert _staged_files() == []

    r = client.post("/api/imports/preview", files={"file": ("a.csv", io.BytesIO(_CSV), "text/csv")},
                    data={"account_id": account_id}, headers={"Accept-Language": "de"})
    assert "konnte nicht gelesen werden" in r.json()["detail"]


def test_reading_an_uploaded_file_again_fails_with_a_message_and_keeps_the_upload(client, monkeypatch):
    from app.importers.csv_importer import CSVImporter

    account_id = _create_account(client)
    preview = _preview(client, "a.csv", _CSV, account_id)
    staged = _staged_files()

    def stumble(_self):
        raise IndexError("list index out of range")

    with monkeypatch.context() as broken:
        broken.setattr(CSVImporter, "parse", stumble)
        reparse = client.post(f"/api/imports/{preview['staging_id']}/reparse",
                              json={"account_id": account_id, "options": {"decimal_separator": ","}})
        assert reparse.status_code == 422 and "IndexError" in reparse.json()["detail"]
        assert client.post(f"/api/imports/{preview['staging_id']}/recognize").status_code == 422
        assert _commit(client, preview, account_id).status_code == 422

    # the file is still there: other options, or another try, can go on
    assert _staged_files() == staged
    assert _stored_documents() == []


def test_an_import_that_fails_leaves_no_statement_without_an_import(client, monkeypatch):
    import pytest

    from app.api.routes import imports as imports_route

    account_id = _create_account(client)
    preview = _preview(client, "statement.csv", _CSV, account_id)

    def fail(*_args, **_kwargs):
        raise RuntimeError("database is locked")

    with monkeypatch.context() as broken:
        broken.setattr(imports_route, "commit_parsed_import", fail)
        with pytest.raises(RuntimeError, match="database is locked"):
            _commit(client, preview, account_id)

    assert _stored_documents() == []  # the copy made before the database commit is gone again
    assert client.get("/api/imports").json() == []
    # ... and the same preview can still be imported
    assert _commit(client, preview, account_id).status_code == 200
    assert len(_stored_documents()) == 1


def test_the_document_stays_when_the_import_was_stored_before_the_failure(client, monkeypatch):
    """A failure after the import reached the database must not take its
    original document away: a stored import always has its file."""
    import pytest

    from app.api.routes import imports as imports_route

    account_id = _create_account(client)
    preview = _preview(client, "statement.csv", _CSV, account_id)
    real_commit = imports_route.commit_parsed_import

    def commit_then_fail(*args, **kwargs):
        real_commit(*args, **kwargs)
        raise RuntimeError("after the commit")

    monkeypatch.setattr(imports_route, "commit_parsed_import", commit_then_fail)
    with pytest.raises(RuntimeError, match="after the commit"):
        _commit(client, preview, account_id)

    [record] = client.get("/api/imports").json()
    assert record["filename"] == "statement.csv"
    assert len(_stored_documents()) == 1


def test_a_document_that_cannot_be_stored_is_explained_and_leaves_no_half_copy(client, monkeypatch):
    from app.api.routes import imports as imports_route

    account_id = _create_account(client)
    preview = _preview(client, "statement.csv", _CSV, account_id)

    def disk_full(_src, dst):
        with open(dst, "wb") as half:
            half.write(b"Date,Descr")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(imports_route.shutil, "copy2", disk_full)
    r = _commit(client, preview, account_id)

    assert r.status_code == 500
    assert "could not be stored" in r.json()["detail"] and "No space left on device" in r.json()["detail"]
    assert _stored_documents() == []
    assert client.get("/api/imports").json() == []
