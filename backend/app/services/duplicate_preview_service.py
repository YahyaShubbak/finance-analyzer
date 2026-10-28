"""Duplicate classification of parsed rows — the single implementation used
by BOTH the import preview and the commit, so what the user reviews is
exactly what gets imported.

Each parsed row gets exactly one of three states:

* **exact_duplicate** — same account, date, amount and description
  fingerprint as an existing transaction, and — when both sides know it —
  the same counterparty (a DKB export describes every card payment as
  "VISA Debitkartenumsatz"; only the payee tells REWE and Lidl apart).
  Counted as a multiset: each existing transaction can be the match of
  only one row, so if a file contains the same row twice (two identical
  3.50 tickets on one day) and the database has it once, one row is a
  duplicate and the other is not. Default decision: skip.
  The same booking read from the other kind of file of the same account —
  a card's PDF statement and its spreadsheet export — counts as an exact
  duplicate too: same amount, the same merchant or description, a date
  up to 3 days apart (one prints the purchase date, the other the booking
  date). The existing booking is completed with what the row adds.
* **possible_duplicate** — no fingerprint match, but an existing
  transaction has the same amount, a date within ±2 days, and the same
  merchant or a clearly overlapping description. Default decision: keep
  (never silently discarded).
* **new**

Recurring charges (same merchant and amount, a month apart) are outside
the date window and therefore never flagged.
"""
from __future__ import annotations

import json
import re
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlmodel import Session, select

from app.db.chunks import chunked
from app.db.models import Account, AccountType, CategoryRule, MerchantRule, RawTransaction, Transaction, TransactionType
from app.i18n import tr
from app.importers.base import ParsedTransaction
from app.normalization.category import (
    CARD_ACCOUNT_EXCLUDED,
    UNSORTED_CATEGORIES,
    categorize,
    sync_default_category_rules,
)
from app.normalization.merchant import normalize_merchant, sync_default_merchant_rules
from app.normalization.review import REFUND_FROM_SOMEONE_ELSE, compute_review_status
from app.services.duplicate_detection import compute_duplicate_fingerprint

POSSIBLE_DUPLICATE_DATE_WINDOW_DAYS = 2
# purchase date (statement) vs booking date (export) of the same booking
CROSS_FILE_DATE_WINDOW_DAYS = 3
_DESCRIPTION_OVERLAP_THRESHOLD = 0.6

# Credit-card statement lines that are the card being paid off (the
# counterpart of the bank account's payment), not a refund.
CARD_PAYMENT_RE = re.compile(
    r"zahlung[\w/ .-]{0,30}erhalten|zahlungseingang|payment[\w/ .-]{0,20}received|payment.{0,5}thank you|"
    r"thank you for your payment|ihre zahlung|besten dank|\blastschrift\b|\beinzug\b|\bausgleich\b|"
    r"\bautopay\b|\bdirect debit\b|\bsaldoausgleich\b|\beinzahlung\b|\baufladung\b|\btop.?up\b|"
    # nothing but the word (Bank Norwegian: "Payment")
    r"^\s*(?:payments?|zahlung)\s*$",
    re.IGNORECASE,
)
# Money arriving on a card account by bank transfer names an IBAN — a
# merchant's refund never does.
_IBAN_IN_TEXT_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,4})?\b")


def is_card_payment(account: Account, amount_minor: int, texts: list[str | None],
                    counterparty_iban: str | None = None, own_ibans: dict[int, set[str]] | None = None) -> bool:
    """Money in on a credit-card account that pays the card (off) — a
    transfer from another account, not a refund. With the user's own IBANs
    known, money sent from someone else's account is no transfer either."""
    if account.account_type != AccountType.CREDIT_CARD or amount_minor <= 0:
        return False
    if own_ibans is not None and paid_by_someone_else(account.id, texts, counterparty_iban, own_ibans):
        return False
    text = " ".join(t for t in texts if t)
    return bool(CARD_PAYMENT_RE.search(text) or _IBAN_IN_TEXT_RE.search(text))


def paid_by_someone_else(account_id: int, texts: list[str | None], counterparty_iban: str | None,
                         own_ibans: dict[int, set[str]]) -> bool:
    """The money came from an IBAN that is none of the user's accounts (say,
    a friend repaying a flight booked for them): a refund of that expense.
    Unknowable while none of the user's own IBANs is known."""
    from app.services.account_recognition import _valid_iban

    known = set().union(*own_ibans.values()) if own_ibans else set()
    if not known:
        return False
    named = {iban for m in _IBAN_IN_TEXT_RE.finditer(" ".join(t for t in texts if t)) if (iban := _valid_iban(m.group(0)))}
    if counterparty_iban:
        named.add(counterparty_iban.replace(" ", "").upper())
    named -= own_ibans.get(account_id, set())  # the card's own account number
    return bool(named) and not (named & known)


@dataclass
class ExistingTransactionInfo:
    id: int
    transaction_date: str
    merchant: str | None
    normalized_description: str
    amount_minor: int
    currency: str


@dataclass
class RowClassification:
    source_row_index: int
    status: str  # "new" | "exact_duplicate" | "possible_duplicate"
    parsed_merchant: str | None
    parsed_category: str | None = None
    transaction_type: TransactionType | None = None
    is_card_payment: bool = False
    paid_by_someone_else: bool = False
    needs_review: bool = False
    review_reason: str | None = None
    match: ExistingTransactionInfo | None = None
    match_reason: str | None = None
    fingerprint: str | None = None
    repeated_in_file: bool = False


def _info(t: Transaction) -> ExistingTransactionInfo:
    return ExistingTransactionInfo(
        id=t.id, transaction_date=t.transaction_date.isoformat(), merchant=t.merchant,
        normalized_description=t.normalized_description, amount_minor=t.amount_minor, currency=t.currency,
    )


def _describe_date_gap(days: int) -> str:
    if days == 0:
        return tr("same date")
    if days == 1:
        return tr("date difference of 1 day")
    return tr("date difference of {days} days", days=days)


def _tokens(text: str | None) -> set[str]:
    return {t for t in re.findall(r"[a-zäöüß]{3,}", (text or "").lower())}


def _descriptions_overlap(a: str | None, b: str | None) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= _DESCRIPTION_OVERLAP_THRESHOLD


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _compact(text: str | None) -> str:
    """Description without spacing, punctuation and long reference numbers:
    a bank's PDF and its spreadsheet export print the same booking as
    "Foo & Bar" and "Foo Bar", or "Foo*Bar" and "Foo *Bar"."""
    text = re.sub(r"\d{4,}", "", (text or "").lower())
    return re.sub(r"[^0-9a-zäöüß]", "", text)


def _existing_counterparties(session: Session, tx_ids: list[int]) -> dict[int, str]:
    """Counterparty recorded at import time (raw extra fields), per
    transaction. Deliberately not the merchant, which the user may have
    corrected since."""
    if not tx_ids:
        return {}
    rows = [
        row for chunk in chunked(tx_ids)
        for row in session.exec(
            select(Transaction.id, RawTransaction.extra_fields_json)
            .join(RawTransaction, RawTransaction.id == Transaction.raw_transaction_id)
            .where(Transaction.id.in_(chunk), RawTransaction.extra_fields_json != None)  # noqa: E711
        ).all()
    ]
    result = {}
    for tx_id, extra_json in rows:
        try:
            counterparty = json.loads(extra_json).get("_counterparty")
        except (ValueError, AttributeError):
            continue
        if counterparty:
            result[tx_id] = _norm(counterparty)
    return result


def default_transaction_type(account: Account, amount_minor: int, is_card_payment: bool) -> TransactionType:
    """Money in on a bank account is income; on a credit card it is a
    refund (reduces spending) or the card being paid off (a transfer)."""
    if amount_minor < 0:
        return TransactionType.EXPENSE
    if account.account_type == AccountType.CREDIT_CARD:
        return TransactionType.TRANSFER if is_card_payment else TransactionType.EXPENSE
    return TransactionType.INCOME


_RULE_SYNC_LOCK = threading.Lock()


def load_rules(session: Session) -> tuple[list[MerchantRule], list[CategoryRule]]:
    # one at a time: files dropped together are previewed in parallel and
    # would otherwise each add the built-in rules
    with _RULE_SYNC_LOCK:
        sync_default_merchant_rules(session)
        sync_default_category_rules(session)
    return list(session.exec(select(MerchantRule)).all()), list(session.exec(select(CategoryRule)).all())


def file_kind(filename: str | None) -> str:
    """"pdf" for a statement, "export" for a spreadsheet (CSV, Excel)."""
    return "pdf" if (filename or "").lower().endswith(".pdf") else "export"


@dataclass(frozen=True)
class SourceFile:
    """Where a booking came from: the kind of file and the period it covers."""
    kind: str
    start: date | None
    end: date | None


def _existing_sources(session: Session, tx_ids: list[int]) -> dict[int, SourceFile]:
    from app.db.models import ImportRecord

    out: dict[int, SourceFile] = {}
    for chunk in chunked(tx_ids):
        for tx_id, filename, start, end in session.exec(
            select(Transaction.id, ImportRecord.filename, ImportRecord.period_start, ImportRecord.period_end)
            .join(RawTransaction, RawTransaction.id == Transaction.raw_transaction_id)
            .join(ImportRecord, ImportRecord.id == RawTransaction.import_id)
            .where(Transaction.id.in_(chunk))
        ).all():
            out[tx_id] = SourceFile(file_kind(filename), start, end)
    return out


def _within(day: date, source: SourceFile | None, slack_before: int = 0) -> bool:
    """`day` lies in the period `source` covers (unknown periods cover everything)."""
    if source is None or source.start is None or source.end is None:
        return True
    return source.start - timedelta(days=slack_before) <= day <= source.end


def booked_in_both(existing_date: date, existing: SourceFile | None, new_date: date, new: SourceFile | None) -> bool:
    """Could two files list the same booking here? Each date must lie in the
    other file's period: consecutive statements may each list an identical
    purchase (two 4.00 tickets on 31.03, one booked on 01.04 and listed with
    its purchase date on the April statement) — two purchases, not one."""
    return _within(new_date, existing) and _within(existing_date, new)


def twin_dates_fit(pdf_date: date, pdf: SourceFile | None, export_date: date, export: SourceFile | None) -> bool:
    """A statement and an export list the same booking only where both cover
    it: the export's date (booking date) in the statement's period — a few
    days before its start too (an export dated by purchase) — and the
    statement's date (purchase date, up to a few days before the booking)
    in the export's period."""
    return (_within(export_date, pdf, slack_before=CROSS_FILE_DATE_WINDOW_DAYS)
            and _within(pdf_date, export, slack_before=CROSS_FILE_DATE_WINDOW_DAYS))


def _same_merchant(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and a.strip().lower() == b.strip().lower()


def classify_import_rows(
    session: Session,
    account: Account | int,
    parsed_transactions: list[ParsedTransaction],
    source_filename: str | None = None,
    source_period: tuple[str | None, str | None] | None = None,
) -> list[RowClassification]:
    """source_filename: the imported file — its bookings may be in the
    database already from the other kind of file (see above)."""
    if isinstance(account, int):
        account = session.get(Account, account)
    merchant_rules, category_rules = load_rules(session)
    from app.services.category_memory import CategoryMemory

    memory = CategoryMemory(session)
    from app.services.account_recognition import own_ibans_by_account

    own_ibans = own_ibans_by_account(session)

    existing_transactions = session.exec(
        select(Transaction).where(
            Transaction.account_id == account.id,
            Transaction.is_duplicate == False,  # noqa: E712
        ).order_by(Transaction.id)
    ).all()
    existing_by_fingerprint: dict[str, list[Transaction]] = defaultdict(list)
    existing_by_compact: dict[tuple, list[Transaction]] = defaultdict(list)
    existing_by_amount: dict[int, list[Transaction]] = defaultdict(list)
    for t in existing_transactions:
        existing_by_fingerprint[t.duplicate_fingerprint].append(t)
        compact = _compact(t.normalized_description)
        if compact:
            existing_by_compact[(t.transaction_date.isoformat(), t.amount_minor, compact)].append(t)
        existing_by_amount[t.amount_minor].append(t)
    existing_counterparty = _existing_counterparties(session, [t.id for t in existing_transactions])
    own_kind = file_kind(source_filename) if source_filename else None
    own_source = SourceFile(own_kind, *(date.fromisoformat(d) if d else None for d in (source_period or (None, None)))) \
        if own_kind else None
    existing_source = _existing_sources(session, [t.id for t in existing_transactions]) if own_kind else {}

    seen_in_file: dict[str, int] = defaultdict(int)
    matched_ids: set[int] = set()
    results: list[RowClassification] = []

    for ptx in parsed_transactions:
        merchant = normalize_merchant(ptx.original_description, merchant_rules, ptx.counterparty)
        row = RowClassification(source_row_index=ptx.source_row_index, status="new", parsed_merchant=merchant)
        results.append(row)

        if ptx.parsed_date is None or ptx.parsed_amount_minor is None:
            continue  # kept as a raw record only; nothing to classify

        amount = ptx.parsed_amount_minor
        texts = [ptx.counterparty, ptx.original_description, (ptx.extra_fields or {}).get("_booking_text")]
        row.is_card_payment = is_card_payment(account, amount, texts, ptx.counterparty_iban, own_ibans)
        row.paid_by_someone_else = (
            account.account_type == AccountType.CREDIT_CARD and amount > 0
            and paid_by_someone_else(account.id, texts, ptx.counterparty_iban, own_ibans)
        )
        row.transaction_type = default_transaction_type(account, amount, row.is_card_payment)
        row.parsed_category = "Transfers" if row.transaction_type == TransactionType.TRANSFER else categorize(
            merchant, ptx.original_description, amount, category_rules,
            is_income=row.transaction_type == TransactionType.INCOME,
            exclude=CARD_ACCOUNT_EXCLUDED if account.account_type == AccountType.CREDIT_CARD else frozenset(),
            merchant_category=(ptx.extra_fields or {}).get("_merchant_category"),
        )
        if row.parsed_category in UNSORTED_CATEGORIES:
            # no rule knows it — but the merchant may be known from other transactions
            row.parsed_category = memory.category_for(
                merchant, row.transaction_type == TransactionType.INCOME) or row.parsed_category
        if row.paid_by_someone_else:
            row.needs_review, row.review_reason = True, REFUND_FROM_SOMEONE_ELSE
        elif row.transaction_type != TransactionType.TRANSFER:
            row.needs_review, row.review_reason = compute_review_status(merchant, row.parsed_category)

        fingerprint = compute_duplicate_fingerprint(account.id, ptx.parsed_date, amount, ptx.original_description)
        row.fingerprint = fingerprint
        seen_in_file[fingerprint] += 1
        row.repeated_in_file = seen_in_file[fingerprint] > 1

        own_counterparty = _norm(ptx.counterparty)
        compact = _compact(ptx.original_description)
        candidates = list(existing_by_fingerprint.get(fingerprint, []))
        if compact:
            candidates += [t for t in existing_by_compact.get((ptx.parsed_date, amount, compact), []) if t not in candidates]
        row_date = date.fromisoformat(ptx.parsed_date)
        exact = next(
            (
                t for t in candidates
                if t.id not in matched_ids
                and (not own_counterparty or not existing_counterparty.get(t.id)
                     or existing_counterparty[t.id] == own_counterparty)
                and booked_in_both(t.transaction_date, existing_source.get(t.id), row_date, own_source)
            ),
            None,
        )
        if exact is not None:
            matched_ids.add(exact.id)
            row.status = "exact_duplicate"
            row.needs_review, row.review_reason = False, None
            row.match = _info(exact)
            row.match_reason = tr("Same account, date, amount, and description as an existing transaction.")
            continue

        new_date = date.fromisoformat(ptx.parsed_date)
        twin = _twin_from_other_file(existing_by_amount.get(amount, []), new_date, merchant, ptx.original_description,
                                     own_counterparty, own_source, existing_source, existing_counterparty, matched_ids)
        if twin is not None:
            existing, gap = twin
            matched_ids.add(existing.id)
            row.status = "exact_duplicate"
            row.needs_review, row.review_reason = False, None
            row.match = _info(existing)
            row.match_reason = tr("The same booking from the other kind of file (statement and export): "
                                  "same amount and merchant, {date_gap}.", date_gap=_describe_date_gap(gap))
            continue

        best: Transaction | None = None
        best_gap: int | None = None
        best_same_merchant = False
        for existing in existing_by_amount.get(amount, []):
            gap = abs((existing.transaction_date - new_date).days)
            if gap > POSSIBLE_DUPLICATE_DATE_WINDOW_DAYS:
                continue
            other_counterparty = existing_counterparty.get(existing.id)
            if own_counterparty and other_counterparty and other_counterparty != own_counterparty:
                continue  # known to be paid to/from someone else
            same_merchant = (
                merchant is not None and existing.merchant is not None
                and existing.merchant.strip().lower() == merchant.strip().lower()
            )
            if not (same_merchant or _descriptions_overlap(existing.normalized_description, ptx.original_description)):
                continue
            if best_gap is None or gap < best_gap:
                best, best_gap, best_same_merchant = existing, gap, same_merchant

        if best is not None:
            row.status = "possible_duplicate"
            row.needs_review, row.review_reason = False, None
            row.match = _info(best)
            similarity = tr("Same merchant") if best_same_merchant else tr("Similar description")
            row.match_reason = tr("{similarity} + same amount + {date_gap}.", similarity=similarity,
                                  date_gap=_describe_date_gap(best_gap))

    return results


def _twin_from_other_file(candidates: list[Transaction], new_date: date, merchant: str | None, description: str | None,
                          own_counterparty: str, own_source: SourceFile | None, existing_source: dict[int, SourceFile],
                          existing_counterparty: dict[int, str], matched_ids: set[int]) -> tuple[Transaction, int] | None:
    """The existing booking this row is, read from the other kind of file
    (statement vs export): the closest in date, not matched yet."""
    if own_source is None:
        return None
    best: tuple[Transaction, int] | None = None
    for existing in candidates:
        other = existing_source.get(existing.id)
        if existing.id in matched_ids or other is None or other.kind == own_source.kind:
            continue
        pdf_side, export_side = ((existing.transaction_date, other), (new_date, own_source)) if other.kind == "pdf" \
            else ((new_date, own_source), (existing.transaction_date, other))
        if not twin_dates_fit(pdf_side[0], pdf_side[1], export_side[0], export_side[1]):
            continue
        gap = abs((existing.transaction_date - new_date).days)
        if gap > CROSS_FILE_DATE_WINDOW_DAYS:
            continue
        other_counterparty = existing_counterparty.get(existing.id)
        if own_counterparty and other_counterparty and other_counterparty != own_counterparty:
            continue
        if not (_same_merchant(merchant, existing.merchant)
                or _descriptions_overlap(existing.normalized_description, description)):
            continue
        if best is None or gap < best[1]:
            best = (existing, gap)
    return best
