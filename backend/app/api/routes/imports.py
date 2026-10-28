"""Import preview/commit endpoints.

Upload -> parse into a staged preview (nothing written to the database
yet) -> user reviews, optionally fixes the column mapping (re-parse) and
confirms -> commit persists via import_service. No parsing, normalization,
or duplicate-classification logic lives here or in the frontend — this
module only wires HTTP to the services.

Each file carries its own target account, so `account_id` is required at
preview time — that's what lets the preview classify duplicates against
the right account's existing data.

Endpoints are plain `def`: parsing and file I/O are blocking and belong in
the thread pool, not on the event loop.
"""
from __future__ import annotations

import dataclasses
import json
import shutil
from datetime import UTC
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import ValidationError
from sqlmodel import Session, select

from app.api.uploads import reject_oversized_request, save_upload
from app.config import settings
from app.db.models import Account, ImportRecord
from app.db.session import get_session, maintenance_lock
from app.i18n import format_date, tr
from app.importers.base import ImportIssue, ParsedImport, ParseOptions
from app.importers.column_detection import layout_label
from app.normalization.review import review_reason_text
from app.schemas.imports import (
    BulkImportRemovalRequest,
    BulkImportRemovalResponse,
    DuplicateMatchRead,
    ImportCommitRequest,
    ImportCommitResponse,
    ImportIssueRead,
    ImportPreviewResponse,
    ImportRecordRead,
    ImportRemovalResponse,
    ParsedTransactionRead,
    ParseOptionsIn,
    ReparseRequest,
    RowClassificationRead,
)
from app.services import import_staging
from app.services.account_recognition import (
    STATEMENT_ON_CARD_ACCOUNT,
    Recognition,
    confirmed_warning_codes,
    ensure_signatures,
    file_signature,
    kind_history,
    recognize_account,
    remember_signature,
)
from app.services.duplicate_preview_service import classify_import_rows
from app.services.import_removal_service import ImportRemovalError, remove_import
from app.services.import_service import (
    ImportServiceError,
    commit_parsed_import,
    document_account_mismatch,
    document_account_warning,
    find_existing_import_by_checksum,
    parse_file,
    purchases_listed_as_positive,
    statement_already_imported,
)
from app.services.import_staging import stored_import_path
from app.services.transfer_detection_service import detect_and_mark_transfers
from app.services.transfer_marking import retype_card_payments

router = APIRouter(prefix="/api/imports", tags=["imports"])


def _account_or_404(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail=tr("Account not found"))
    return account


def _staged_or_404(staging_id: str) -> Path:
    try:
        return import_staging.find_staged_file(staging_id)
    except import_staging.StagingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _build_preview(
    session: Session, staging_id: str, staged_path: Path, account: Account | None, options: ParseOptions,
    parsed: ParsedImport | None = None, recognition: Recognition | None = None,
) -> ImportPreviewResponse:
    if parsed is None:
        parsed = parse_file(staged_path, original_filename=import_staging.original_filename(staged_path), options=options)
    auto_inverted = False
    if account is not None and options.invert_signs is None and purchases_listed_as_positive(parsed, account):
        # Card exports often list purchases as positive numbers (the issuer's
        # view). Unless the user decided otherwise in the dialog, read them
        # the app's way round — and say so, so it can be undone.
        options = dataclasses.replace(options, invert_signs=True)
        import_staging.save_options(staging_id, options)  # the commit parses exactly the same way
        parsed = parse_file(staged_path, original_filename=import_staging.original_filename(staged_path), options=options)
        auto_inverted = True

    existing = find_existing_import_by_checksum(session, parsed.file_checksum)
    if existing is not None:
        parsed.issues.insert(0, ImportIssue(severity="error", message=tr(
            "This file appears to have already been imported ({count} transactions, on {date}).",
            count=existing.detected_transaction_count, date=format_date(existing.imported_at),
        )))
    mismatch = (document_account_mismatch(parsed, account) or statement_already_imported(session, parsed, account)) \
        if account else None
    if mismatch:
        parsed.issues.insert(0, ImportIssue(severity="error", message=mismatch))
    elsewhere = _iban_of_another_account(session, staged_path, parsed, account) if account and not recognition else None
    if elsewhere:
        parsed.issues.insert(0, ImportIssue(severity="warning", message=tr(
            "This file names the IBAN of your account '{other}', not of '{account}'. "
            "Check that you chose the right account.", other=elsewhere.name, account=account.name,
        )))
    account_warning = document_account_warning(parsed, account) if account else None
    if account_warning and not (recognition and STATEMENT_ON_CARD_ACCOUNT in recognition.confirmed_warnings):
        parsed.issues.insert(0, ImportIssue(severity="warning", message=account_warning))
    if auto_inverted:
        parsed.issues.append(ImportIssue(severity="warning", message=tr(
            "Purchases are listed as positive numbers in this credit-card file, so all amounts were inverted "
            "(purchases negative, refunds and payments positive). If that is wrong, open \"Adjust columns / "
            "formats\" and untick \"Invert all amounts\"."
        )))

    row_classifications = []
    counts = {"new": 0, "exact_duplicate": 0, "possible_duplicate": 0}
    needs_review_count = 0
    total_check = parsed.total_check
    if account is not None and not parsed.ambiguous and not parsed.has_errors:
        classifications = classify_import_rows(session, account, parsed.transactions, parsed.filename,
                                                   (parsed.period_start, parsed.period_end))
        if total_check is None and parsed.statement_total_minor is not None:
            # card statement: purchases minus refunds (not the card's payment) == the statement amount
            payments = {c.source_row_index for c in classifications if c.is_card_payment}
            spent = -sum(t.parsed_amount_minor or 0 for t in parsed.transactions if t.source_row_index not in payments)
            total_check = {"kind": "statement_total",
                           "ok": spent == parsed.statement_total_minor and parsed.unusable_row_count == 0,
                           "difference_minor": parsed.statement_total_minor - spent}
        for c in classifications:
            if c.fingerprint is None:
                continue  # unusable row (no date/amount) — reported via unusable_row_count
            counts[c.status] += 1
            needs_review_count += int(c.needs_review)
            row_classifications.append(RowClassificationRead(
                source_row_index=c.source_row_index,
                status=c.status,
                parsed_merchant=c.parsed_merchant,
                parsed_category=c.parsed_category,
                transaction_type=c.transaction_type.value if c.transaction_type else None,
                needs_review=c.needs_review,
                review_reason=review_reason_text(c.review_reason),
                match=DuplicateMatchRead(
                    transaction_id=c.match.id,
                    transaction_date=c.match.transaction_date,
                    merchant=c.match.merchant,
                    normalized_description=c.match.normalized_description,
                    amount_minor=c.match.amount_minor,
                    currency=c.match.currency,
                ) if c.match else None,
                match_reason=c.match_reason,
                repeated_in_file=c.repeated_in_file,
            ))

    warning_count = sum(1 for i in parsed.issues if i.severity == "warning")
    auto_import = (
        recognition is not None and account is not None
        and (recognition.by in ("iban", "history") or (recognition.by == "format" and recognition.verified))
        and not parsed.ambiguous and not parsed.has_errors
        and warning_count == 0 and parsed.unusable_row_count == 0 and counts["possible_duplicate"] == 0
        # (a file whose bookings all exist already still adds to them: statement, details, places)
        and counts["new"] + counts["exact_duplicate"] > 0 and (total_check is None or bool(total_check.get("ok")))
    )
    return ImportPreviewResponse(
        staging_id=staging_id,
        filename=parsed.filename,
        account_id=account.id if account else None,
        account_name=account.name if account else None,
        account_recognized=recognition.by if recognition else None,
        auto_import=auto_import,
        review_reasons=_review_reasons(session, staged_path, parsed, account, counts, total_check, warning_count),
        page_count=parsed.page_count,
        layout_lines=parsed.layout_lines,
        source_rows=parsed.source_rows,
        document_type=parsed.document_type,
        detected_columns=parsed.detected_columns,
        detected_layout=layout_label(parsed.detected_layout),
        period_start=parsed.period_start,
        period_end=parsed.period_end,
        transaction_count=len(parsed.transactions),
        transactions=[
            ParsedTransactionRead(**{
                k: v for k, v in dataclasses.asdict(t).items() if k in ParsedTransactionRead.model_fields
            }, details=(t.extra_fields or {}).get("_details"))
            for t in parsed.transactions
        ],
        issues=[ImportIssueRead(severity=i.severity, message=i.message, row_index=i.row_index) for i in parsed.issues],
        ambiguous=parsed.ambiguous,
        has_errors=parsed.has_errors,
        statement_total_minor=parsed.statement_total_minor,
        other_totals=parsed.other_totals,
        total_check=total_check,
        available_columns=parsed.available_columns,
        header_row_index=parsed.header_row_index,
        date_format=parsed.date_format,
        date_format_candidates=parsed.date_format_candidates,
        decimal_separator=parsed.decimal_separator,
        needs_decimal_separator=parsed.needs_decimal_separator,
        options=ParseOptionsIn(**options.to_dict()),
        new_count=counts["new"],
        exact_duplicate_count=counts["exact_duplicate"],
        possible_duplicate_count=counts["possible_duplicate"],
        needs_review_count=needs_review_count,
        unusable_row_count=parsed.unusable_row_count,
        warning_count=warning_count,
        row_classifications=row_classifications,
    )


def _review_reasons(session: Session, staged_path: Path, parsed: ParsedImport, account: Account | None,
                    counts: dict, total_check: dict | None, warning_count: int) -> list[str]:
    """Why the import review should open by itself: a kind of file this
    account hasn't had (and that wasn't checked), or something to look at."""
    reasons = []
    if account is not None and not parsed.has_errors:
        seen, verified = kind_history(session, file_signature(staged_path, parsed), account.id)
        if not seen and not verified:
            reasons.append("new_kind")
    if not parsed.transactions:
        reasons.append("no_bookings")
    if any(line["role"] == "unreadable" for line in parsed.layout_lines):
        reasons.append("unreadable_lines")
    if parsed.unusable_row_count:
        reasons.append("unusable_rows")
    if total_check is not None and not total_check.get("ok"):
        reasons.append("check_failed")
    if warning_count:
        reasons.append("warnings")
    return reasons


def _iban_of_another_account(session: Session, staged_path: Path, parsed: ParsedImport, account: Account) -> Account | None:
    """The user's other account whose IBAN the file prints as its own, when
    the chosen account's IBAN isn't printed."""
    own = set(file_signature(staged_path, parsed).identifiers)
    if account.iban and f"iban:{account.iban}" in own:
        return None
    others = [a for a in session.exec(select(Account)).all()
              if a.id != account.id and a.iban and f"iban:{a.iban}" in own]
    return others[0] if len(others) == 1 else None


def _parse_options_form(raw: str | None) -> ParseOptions:
    if not raw:
        return ParseOptions()
    try:
        return ParseOptions(**ParseOptionsIn.model_validate(json.loads(raw)).model_dump())
    except (ValueError, ValidationError, RecursionError) as exc:
        raise HTTPException(status_code=422, detail=tr("Invalid import options: {error}", error=exc)) from exc


@router.post("/preview", response_model=ImportPreviewResponse)
def preview_import(
    request: Request,
    file: UploadFile,
    account_id: int | None = Form(None),
    options: str | None = Form(None),
    session: Session = Depends(get_session),
):
    """Without account_id the account is recognized from the file when
    possible (see app.services.account_recognition); otherwise the preview
    comes back without account, for the user to choose one (reparse)."""
    settings.ensure_directories()
    account = _account_or_404(session, account_id) if account_id is not None else None

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in settings.allowed_upload_extensions:
        raise HTTPException(
            status_code=400,
            detail=tr("Unsupported file type '{suffix}'. Allowed: {allowed}", suffix=suffix,
                      allowed=", ".join(settings.allowed_upload_extensions)),
        )
    reject_oversized_request(request, settings.max_upload_size_bytes)
    parse_options = _parse_options_form(options)

    import_staging.purge_stale_staging_files()
    staging_id = import_staging.new_staging_id()
    staged_path = import_staging.staged_file_path(staging_id, file.filename or f"upload{suffix}")
    save_upload(file, staged_path, settings.max_upload_size_bytes)
    import_staging.save_display_name(staging_id, file.filename or "")
    import_staging.save_options(staging_id, parse_options)

    if account is not None:
        return _build_preview(session, staging_id, staged_path, account, parse_options)
    return _recognized_preview(session, staging_id, staged_path, parse_options)


def _recognized_preview(session: Session, staging_id: str, staged_path: Path,
                        parse_options: ParseOptions) -> ImportPreviewResponse:
    """The preview with the account recognized from the file, read the way
    the previous file of its kind was read — when the user chose no options."""
    parsed = parse_file(staged_path, original_filename=import_staging.original_filename(staged_path), options=parse_options)
    ensure_signatures(session)
    recognition = recognize_account(session, parsed, file_signature(staged_path, parsed))
    if recognition is None:
        return _build_preview(session, staging_id, staged_path, None, parse_options, parsed=parsed)
    if recognition.options is not None and parse_options == ParseOptions():
        # read the way the previous file of this kind was read (its column mapping, signs, ...)
        parse_options = recognition.options
        import_staging.save_options(staging_id, parse_options)
        parsed = None
    return _build_preview(session, staging_id, staged_path, recognition.account, parse_options,
                          parsed=parsed, recognition=recognition)


@router.post("/{staging_id}/recognize", response_model=ImportPreviewResponse)
def recognize_again(staging_id: str, session: Session = Depends(get_session)):
    """Read an uploaded file again as files of its kind are read now. Several
    files dropped at once are all read on upload; when the user then teaches
    or confirms one of them, the others learn it this way."""
    staged_path = _staged_or_404(staging_id)
    options = ParseOptions()
    import_staging.save_options(staging_id, options)
    return _recognized_preview(session, staging_id, staged_path, options)


@router.post("/{staging_id}/reparse", response_model=ImportPreviewResponse)
def reparse_import(staging_id: str, payload: ReparseRequest, session: Session = Depends(get_session)):
    """Re-run the preview for an already uploaded file with the user's
    column mapping / date format / decimal separator, or for a different
    target account — without uploading the file again."""
    staged_path = _staged_or_404(staging_id)
    account = _account_or_404(session, payload.account_id) if payload.account_id is not None else None
    options = ParseOptions(**payload.options.model_dump())
    import_staging.save_options(staging_id, options)
    return _build_preview(session, staging_id, staged_path, account, options)


def _page_png(path: Path, page: int, zoom: float) -> Response:
    """One page of a PDF as an image, for the import review (rendered here, so
    the browser needs no PDF viewer — and the file never leaves the app)."""
    import pymupdf

    if path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail=tr("Only PDF files have pages."))
    try:
        with pymupdf.open(path) as doc:
            if not 0 <= page < doc.page_count:
                raise HTTPException(status_code=404, detail=tr("This page doesn't exist."))
            png = doc[page].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — a damaged PDF
        raise HTTPException(status_code=422, detail=tr("Could not open the PDF — it may be damaged or not a PDF file.")) from exc
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=600"})


@router.get("/staging/{staging_id}/pages/{page}")
def staged_page(staging_id: str, page: int, zoom: float = Query(1.5, ge=0.5, le=3)):
    """A page of an uploaded (not yet imported) PDF."""
    return _page_png(_staged_or_404(staging_id), page, zoom)


@router.get("/{import_id}/pages/{page}")
def imported_page(import_id: int, page: int, zoom: float = Query(1.5, ge=0.5, le=3),
                  session: Session = Depends(get_session)):
    """A page of an imported PDF (its stored original)."""
    record = session.get(ImportRecord, import_id)
    path = stored_import_path(record.stored_path) if record else None
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail=tr("The original file is no longer there."))
    return _page_png(path, page, zoom)


@router.delete("/staging/{staging_id}", status_code=204)
def discard_staged_import(staging_id: str):
    """The user cancelled the preview: delete the uploaded statement now
    rather than waiting for the periodic purge."""
    try:
        import_staging.discard(staging_id)
    except import_staging.StagingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/commit", response_model=ImportCommitResponse)
def commit_import(payload: ImportCommitRequest, session: Session = Depends(get_session)):
    # Serialized: a double-click or a second tab committing the same file
    # must see the first commit's checksum and be rejected as a duplicate.
    with maintenance_lock:
        staged_path = _staged_or_404(payload.staging_id)
        original_filename = import_staging.original_filename(staged_path)
        account = _account_or_404(session, payload.account_id)

        options = import_staging.load_options(payload.staging_id)
        parsed = parse_file(staged_path, original_filename=original_filename, options=options)
        decision_map = {d.source_row_index: d.decision for d in payload.row_decisions}
        if payload.auto and not parsed.has_errors and any(
            c.status == "possible_duplicate"
            for c in classify_import_rows(session, account, parsed.transactions, parsed.filename,
                                                   (parsed.period_start, parsed.period_end))
        ):
            raise HTTPException(status_code=409, detail=tr(
                "Some rows of this file now look like transactions that are already imported. "
                "Please check the preview and import it yourself."
            ))
        signature = file_signature(staged_path, parsed)

        # The original document is stored before the database commit, so a
        # committed import can never point at a missing file.
        settings.ensure_directories()
        stored_name = f"{payload.staging_id[:12]}_{import_staging.sanitize_filename(original_filename)}"
        final_path = settings.imports_dir / stored_name
        shutil.copy2(staged_path, final_path)
        try:
            result = commit_parsed_import(
                session, parsed, payload.account_id, stored_path=stored_name, row_decisions=decision_map,
            )
        except ImportServiceError as exc:
            final_path.unlink(missing_ok=True)
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        # the next file of this kind is recognized and read the same way
        _seen, verified_before = kind_history(session, signature, account.id)
        remember_signature(result.import_record, signature, options, confirmed_warning_codes(parsed, account),
                           verified=payload.verified or verified_before)
        session.add(result.import_record)
        session.commit()
        import_staging.discard(payload.staging_id)
        # The file's own IBAN is known now: card payments read before as
        # someone else's (or the other way round) change type.
        if retype_card_payments(session):
            detect_and_mark_transfers(session)

    return ImportCommitResponse(
        import_id=result.import_record.id,
        filename=result.import_record.filename,
        transactions_created=result.transactions_created,
        duplicates_flagged=result.duplicates_flagged,
        rows_skipped=result.rows_skipped,
        credit_card_statement_id=result.credit_card_statement.id if result.credit_card_statement else None,
        transactions_enriched=result.transactions_enriched,
    )


@router.get("", response_model=list[ImportRecordRead])
def list_imports(session: Session = Depends(get_session)):
    records = session.exec(select(ImportRecord).order_by(ImportRecord.imported_at.desc())).all()
    accounts_by_id = {a.id: a.name for a in session.exec(select(Account)).all()}
    return [
        ImportRecordRead(
            id=r.id, filename=r.filename, document_type=r.document_type,
            account_id=r.account_id, account_name=accounts_by_id.get(r.account_id, "Unknown"),
            # Stored as naive UTC; say so explicitly so browsers convert to local time.
            imported_at=r.imported_at.replace(tzinfo=UTC).isoformat(),
            period_start=r.period_start.isoformat() if r.period_start else None,
            period_end=r.period_end.isoformat() if r.period_end else None,
            status=r.status.value, detected_transaction_count=r.detected_transaction_count,
        )
        for r in records
    ]


@router.post("/remove", response_model=BulkImportRemovalResponse)
def remove_imports_route(payload: BulkImportRemovalRequest, session: Session = Depends(get_session)):
    """Removes several imports at once (e.g. all of one account), each
    exactly like the single removal below. Unknown ids are refused before
    anything is removed."""
    ids = list(dict.fromkeys(payload.import_ids))
    transactions = 0
    with maintenance_lock:  # checked inside: a removal running at the same time may take some first
        known = set(session.exec(select(ImportRecord.id).where(ImportRecord.id.in_(ids))).all())
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise HTTPException(status_code=404, detail=tr("Unknown import_id={import_id}", import_id=unknown[0]))
        for import_id in ids:
            transactions += remove_import(session, import_id).transactions_removed
    return BulkImportRemovalResponse(imports_removed=len(ids), transactions_removed=transactions)


@router.delete("/{import_id}", response_model=ImportRemovalResponse)
def remove_import_route(import_id: int, session: Session = Depends(get_session)):
    """Removes an import and everything derived from it — transfer pairs
    and reconciliations referencing removed transactions are safely
    reverted/recomputed, never left dangling — plus the stored original
    document."""
    with maintenance_lock:
        try:
            result = remove_import(session, import_id)
        except ImportRemovalError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ImportRemovalResponse(
        import_id=result.import_id,
        filename=result.filename,
        transactions_removed=result.transactions_removed,
        raw_transactions_removed=result.raw_transactions_removed,
        transfer_partners_reverted=result.transfer_partners_reverted,
        statements_removed=result.statements_removed,
        reconciliations_recomputed=result.reconciliations_recomputed,
    )
