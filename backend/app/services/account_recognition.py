"""Which account a statement belongs to, so that a kind of file imported
before goes to its account without asking.

A file's *signature* is what kind of file it is (PDF layout or spreadsheet
format and columns, document type) plus the account identifiers its header
prints — the part before the first booking: IBANs and masked card numbers
("xxxx xxxxxx x1234"). Identifiers in the bookings (a transfer's
counterparty, the card a bank debit settles) are not the file's own.

An account is recognized
* by an IBAN in the header that belongs to exactly one account, or
* by earlier imports of the same kind: all of them on one account, and —
  when the file prints identifiers — sharing one of them. A file printing
  none is only *suggested* for that account (by="format", confirmed by the
  user) when another account of the same type exists (so a second card
  of the same issuer is not taken for the first); or, after a bank changed
  how it writes its files, earlier imports printing exactly the same
  identifiers.
Anything less certain is left to the user.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlmodel import Session, select

from app.db.models import Account, AccountType, DocumentType, ImportRecord, ImportStatus
from app.importers.base import ParsedImport, ParseOptions
from app.importers.csv_importer import CSVImporter

logger = logging.getLogger("finance")

# from Norway's 15 characters to 34 (the check digits tell an IBAN from other codes)
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
# A card number with most digits masked: "xxxx xxxxxx x1234", "**** **** **** 1234", "4111 XXXX XXXX 1234".
_CARD_RE = re.compile(r"(?<![\w*•])[\dXx*•]+(?:[ -][\dXx*•]+){0,4}(?![\w*•])")
_MASK = "Xx*•"


@dataclass(frozen=True)
class Signature:
    key: str  # what kind of file
    identifiers: tuple[str, ...]  # "iban:DE..", "card:1234"


@dataclass(frozen=True)
class Recognition:
    account: Account
    # "iban": an IBAN in the file; "history": earlier files of this kind printing the same account
    # or card number; "format": earlier files of the same format only — a second account at the
    # same bank would look the same, so the user confirms (unless no other account could be meant)
    by: str
    options: ParseOptions | None = None  # how the last file of this kind was read
    confirmed_warnings: frozenset[str] = frozenset()  # warnings accepted for it before
    verified: bool = False  # the user checked this kind of file and said "don't ask again"


def _valid_iban(text: str) -> str | None:
    iban = re.sub(r"\s+", "", text).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
        return None
    digits = "".join(str(int(ch, 36)) for ch in iban[4:] + iban[:4])
    return iban if int(digits) % 97 == 1 else None


# "VISA ending 1234", "Karte endet auf 1234", "Kartennummer endend mit 1234"
_CARD_ENDING_RE = re.compile(r"(?i)\b(?:ending(?: in)?|endet auf|endend (?:auf|mit)|endziffern?)\s*[:#]?\s*(\d{4})\b")


def _identifiers(text: str) -> set[str]:
    found = {f"iban:{iban}" for m in _IBAN_RE.finditer(text) if (iban := _valid_iban(m.group(0)))}
    found |= {f"card:{m.group(1)}" for m in _CARD_ENDING_RE.finditer(text)}
    for m in _CARD_RE.finditer(text):
        number = re.sub(r"[ -]", "", m.group(0))
        ending = re.search(r"\d{3,4}$", number)
        if 13 <= len(number) <= 19 and sum(ch in _MASK for ch in number) >= 4 and ending:
            found.add(f"card:{ending.group(0)}")
    return found


def _header_text(path: Path, parsed: ParsedImport) -> tuple[str, bool]:
    """The part of the file before the bookings start, as text — and
    whether that start was found (otherwise the text may include bookings)."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            import pymupdf

            with pymupdf.open(path) as doc:
                return _before_first_booking([page.get_text("text") for page in doc], parsed)
        if suffix == ".csv" and parsed.header_row_index:
            return "\n".join(CSVImporter._decode(path.read_bytes()).splitlines()[: parsed.header_row_index]), True
        if suffix == ".xlsx" and parsed.header_row_index:
            import openpyxl

            workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
            try:
                rows = workbook.worksheets[0].iter_rows(max_row=parsed.header_row_index, values_only=True)
                return "\n".join(" ".join(str(v) for v in row if v is not None) for row in rows), True
            finally:
                workbook.close()
    except Exception:  # noqa: BLE001 — an unreadable header just means no identifiers
        logger.debug("Could not read the header of %s", path.name, exc_info=True)
    return "", True


def _before_first_booking(pages: list[str], parsed: ParsedImport) -> tuple[str, bool]:
    """A PDF's text up to its first booking: where a statement prints its
    own account (a report may start with an overview page). Found by the
    first booking's text; without it, the first page (bookings included)."""
    first = next((t.original_description for t in parsed.transactions if t.original_description), None)
    words = (first or "").split()[:3]
    if words:
        pattern = re.compile(r"\s+".join(re.escape(w) for w in words))
        seen = []
        for text in pages:
            m = pattern.search(text)
            if m:
                return "\n".join([*seen, text[: m.start()]]), True
            seen.append(text)
    return (pages[0] if pages else ""), False


# words in a PDF's producer/creator that don't name the software
_NOT_A_PRODUCER = frozenset({"producer", "creator", "pdf", "library", "version", "technologies", "inc", "gmbh",
                             "ag", "cxm", "for", "the"})


def _pdf_producer(path: Path) -> str:
    """The family of the software that wrote the PDF ("quadient" for
    "Quadient CXM AG~Inspire~15.0.739.3" and "Producer|Quadient~Inspire~16.0.759.6"):
    a bank's statements keep it while its version changes."""
    import pymupdf

    try:
        with pymupdf.open(path) as doc:
            meta = doc.metadata or {}
    except Exception:  # noqa: BLE001 — a broken PDF; its parse result reports the problem
        return ""
    words = re.findall(r"[a-z]{3,}", f"{meta.get('producer') or ''} {meta.get('creator') or ''}".lower())
    return next((w for w in words if w not in _NOT_A_PRODUCER), "")


_MONTHS = re.compile(r"(?i)\b(?:jan|feb|mär|maer|mar|apr|mai|may|jun|jul|aug|sep|okt|oct|nov|dez|dec)[a-zä]*\b")


def _title_of(header: str) -> str:
    """The first two lines with words, without numbers and month names —
    the same for every statement of a bank's layout."""
    lines = []
    for line in header.splitlines():
        words = re.sub(r"[^A-Za-zÄÖÜäöüß ]+", " ", _MONTHS.sub(" ", line)).upper().split()
        if len(" ".join(words)) >= 4:
            lines.append(" ".join(words))
        if len(lines) == 2:
            break
    return "|".join(lines)


def file_signature(path: Path, parsed: ParsedImport) -> Signature:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        # the software that wrote the PDF tells one bank's statements from another's
        kind_of_file = parsed.signature_kind or f"{parsed.document_type.value}|{parsed.detected_layout or ''}"
        kind = f"pdf|{kind_of_file}|{_pdf_producer(path)}"
    else:
        columns = "|".join(sorted(c.strip().lower() for c in parsed.available_columns))
        kind = f"{suffix[1:]}|{parsed.detected_layout or ''}|{columns}"
    header, cut = _header_text(path, parsed)
    if suffix == ".pdf" and kind.startswith("pdf|unknown|"):
        # no reader knows it: its title tells one bank's statements from another's
        # (two banks may use the same PDF software — each keeps its own taught reader)
        kind += "|" + _title_of(header)
    own = _identifiers(header)
    if not cut:
        # the text may include bookings: a counterparty's IBAN is not the file's own
        for t in parsed.transactions:
            own -= _identifiers(" ".join(filter(None, [
                t.original_description, (t.extra_fields or {}).get("_details"), t.counterparty_iban,
            ])))
    own = sorted(own)
    return Signature(key=hashlib.sha256(kind.encode()).hexdigest()[:24], identifiers=tuple(own))


def remember_signature(record: ImportRecord, signature: Signature, options: ParseOptions,
                       confirmed_warnings: list[str], verified: bool = False) -> None:
    record.source_key = signature.key
    record.source_info_json = json.dumps({
        "identifiers": list(signature.identifiers),
        "options": options.to_dict(),
        "confirmed_warnings": confirmed_warnings,
        "verified": verified,
    }, ensure_ascii=False)


def kind_history(session: Session, signature: Signature, account_id: int) -> tuple[bool, bool]:
    """(imported before into this account, checked and "don't ask again")
    for files of this kind."""
    records = session.exec(select(ImportRecord).where(
        ImportRecord.source_key == signature.key, ImportRecord.account_id == account_id,
        ImportRecord.status == ImportStatus.IMPORTED,
    )).all()
    return bool(records), any(_info(r).get("verified") for r in records)


def _info(record: ImportRecord) -> dict:
    try:
        info = json.loads(record.source_info_json) if record.source_info_json else {}
    except ValueError:
        return {}
    return info if isinstance(info, dict) else {}


def own_ibans_by_account(session: Session) -> dict[int, set[str]]:
    """The IBANs of each of the user's accounts: the one entered for it and
    those printed in the headers of its imported files."""
    result: dict[int, set[str]] = {}
    for account_id, iban in session.exec(select(Account.id, Account.iban).where(Account.iban != None)).all():  # noqa: E711
        result.setdefault(account_id, set()).add(iban.replace(" ", "").upper())
    for record in session.exec(select(ImportRecord).where(
        ImportRecord.account_id != None, ImportRecord.source_info_json != None,  # noqa: E711
    )).all():
        named = {i[len("iban:"):] for i in _info(record).get("identifiers") or () if i.startswith("iban:")}
        if named:
            result.setdefault(record.account_id, set()).update(named)
    return result


def _replaced_card(imported: list[ImportRecord], signature: Signature, parsed: ParsedImport) -> list[ImportRecord]:
    """A statement of a known kind printing only numbers never seen before —
    a replaced card, a new layout of its header: the earlier statements of
    the kind, when this one's printed period comes after all of theirs. A
    second card of the same bank would run side by side, so overlapping
    periods (or files without a printed period) are asked about."""
    if not (parsed.page_count and parsed.period_start and parsed.period_end):  # a PDF statement
        return []
    known = set().union(*(set(_info(r).get("identifiers") or ()) for r in imported))
    if set(signature.identifiers) & known:
        return []  # numbers of other files: not a successor of these
    same_key = [r for r in imported if r.source_key == signature.key]
    start = date.fromisoformat(parsed.period_start)
    if not same_key or any(r.period_end is None or r.period_end > start for r in same_key):
        return []
    return same_key


def recognize_account(session: Session, parsed: ParsedImport, signature: Signature) -> Recognition | None:
    accounts = [a for a in session.exec(select(Account).where(Account.is_archived == False)).all()]  # noqa: E712
    fits = [a for a in accounts if parsed.document_type != DocumentType.CREDIT_CARD_STATEMENT
            or a.account_type == AccountType.CREDIT_CARD]
    by_iban = {f"iban:{a.iban}": a for a in fits if a.iban}
    named = {by_iban[i].id: by_iban[i] for i in signature.identifiers if i in by_iban}
    if len(named) > 1:
        named = {}  # the header names several of the user's accounts (an overview): history decides

    imported = session.exec(
        select(ImportRecord)
        .where(ImportRecord.status == ImportStatus.IMPORTED, ImportRecord.source_key != None)  # noqa: E711
        .order_by(ImportRecord.imported_at.desc())
    ).all()
    current = set(signature.identifiers)
    same_kind = [r for r in imported if r.source_key == signature.key
                 and (not current or current & set(_info(r).get("identifiers") or ()))]
    if not same_kind and current:
        # the same accounts printed, the file written differently (the bank changed its software)
        same_kind = [r for r in imported if r.document_type == parsed.document_type
                     and set(_info(r).get("identifiers") or ()) == current]
    successor = False
    if not same_kind and current:
        same_kind = _replaced_card(imported, signature, parsed)
        successor = bool(same_kind)
    history_accounts = {r.account_id for r in same_kind}

    fits_by_id = {a.id: a for a in fits}
    if named:
        account = next(iter(named.values()))
        if history_accounts - {account.id}:
            return None  # earlier files of this kind went elsewhere: ask
        by = "iban"
    elif len(history_accounts) == 1 and next(iter(history_accounts)) in fits_by_id:
        account = fits_by_id[next(iter(history_accounts))]
        same_type = [a for a in fits if a.account_type == account.account_type]
        by = "replaced" if successor else "history" if current or len(same_type) == 1 else "format"
    else:
        return None

    previous = next((r for r in same_kind if r.account_id == account.id), None)
    options = confirmed = None
    if previous is not None:
        info = _info(previous)
        options = ParseOptions.from_dict(info.get("options")) if info.get("options") else None
        confirmed = frozenset(info.get("confirmed_warnings") or ())
    # a replaced card is confirmed once by the user, even when this kind of file needs no look
    verified = not successor and any(_info(r).get("verified") for r in same_kind if r.account_id == account.id)
    return Recognition(account=account, by=by, options=options, confirmed_warnings=confirmed or frozenset(),
                       verified=verified)


STATEMENT_ON_CARD_ACCOUNT = "statement_on_card_account"


def confirmed_warning_codes(parsed: ParsedImport, account: Account) -> list[str]:
    """Warnings that, once accepted for a kind of file on an account, need
    no confirmation again (unlike a balance that doesn't add up)."""
    from app.services.import_service import document_account_warning

    return [STATEMENT_ON_CARD_ACCOUNT] if document_account_warning(parsed, account) else []


def ensure_signatures(session: Session) -> None:
    """Imports made before signatures existed: read their stored files once."""
    from app.services.import_service import parse_file, purchases_listed_as_positive
    from app.services.import_staging import stored_import_path

    records = session.exec(
        select(ImportRecord).where(ImportRecord.source_key == None, ImportRecord.status == ImportStatus.IMPORTED)  # noqa: E711
    ).all()
    for record in records:
        record.source_key = ""  # tried — also when the file is gone or unreadable
        path = stored_import_path(record.stored_path)
        account = session.get(Account, record.account_id) if record.account_id else None
        if path is not None and path.exists() and account is not None:
            try:
                parsed = parse_file(path, original_filename=record.filename)
                options = ParseOptions(invert_signs=True) if purchases_listed_as_positive(parsed, account) else ParseOptions()
                remember_signature(record, file_signature(path, parsed), options, confirmed_warning_codes(parsed, account))
            except Exception:  # noqa: BLE001 — that file just won't help recognizing the next one
                logger.debug("Could not read imported file %s", record.filename, exc_info=True)
        session.add(record)
    if records:
        session.commit()


#: raise when file signatures are worked out differently: imported files are signed again on start-up
SIGNATURES_VERSION = "3"
#: in the data folder: the SIGNATURES_VERSION the imported files were last signed with
SIGNATURES_MARKER = ".signatures_version"


def refresh_signatures(session: Session, force: bool = False) -> int:
    """On start-up, once per SIGNATURES_VERSION (force: after a restore): sign
    the imported files again — what was learned about them (options,
    accepted warnings, "don't ask again") stays. Never keeps the app from starting."""
    from app.config import settings
    from app.services.import_service import parse_file
    from app.services.import_staging import stored_import_path

    marker = settings.data_dir / SIGNATURES_MARKER
    try:
        if not force and marker.exists() and marker.read_text(encoding="utf-8").strip() == SIGNATURES_VERSION:
            return 0
        ensure_signatures(session)
        signed = 0
        for record in session.exec(select(ImportRecord).where(
            ImportRecord.status == ImportStatus.IMPORTED, ImportRecord.source_key != None,  # noqa: E711
            ImportRecord.source_key != "",
        )).all():
            path = stored_import_path(record.stored_path)
            if path is None or not path.exists():
                continue
            info = _info(record)
            try:
                options = ParseOptions.from_dict(info.get("options")) if info.get("options") else None
                signature = file_signature(path, parse_file(path, original_filename=record.filename, options=options))
            except Exception:  # noqa: BLE001 — that file keeps its old signature
                logger.debug("Could not sign %s again", record.filename, exc_info=True)
                continue
            record.source_key = signature.key
            record.source_info_json = json.dumps({**info, "identifiers": list(signature.identifiers)}, ensure_ascii=False)
            session.add(record)
            signed += 1
        session.commit()
        marker.write_text(SIGNATURES_VERSION, encoding="utf-8")
        if signed:
            logger.info("Signed %d imported files again", signed)
        return signed
    except Exception:  # noqa: BLE001
        session.rollback()
        logger.exception("Could not sign the imported files again")
        return 0
