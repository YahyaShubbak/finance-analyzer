from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import selectinload
from sqlmodel import Session, func, select

from app.db.models import (
    Account,
    CategoryRule,
    RawTransaction,
    Transaction,
    TransactionType,
    UserCorrection,
    utcnow,
)
from app.db.session import fold_plain, fold_text, get_session
from app.i18n import tr
from app.normalization.review import review_reason_text
from app.reconciliation.engine import reconcile_statement
from app.schemas.transaction import (
    AssignCategoryRequest,
    AssignCategoryResponse,
    CategoryRuleRead,
    CreateCategoryRuleRequest,
    CreateMerchantRuleRequest,
    CreateRuleResponse,
    MerchantRuleRead,
    ReapplyRulesResponse,
    ReviewGroupRead,
    ReviewGroupsResponse,
    TransactionListResponse,
    TransactionRead,
    TransactionUpdate,
)
from app.services import review_service
from app.services.category_suggestion import UnsortedSuggestions
from app.services.points_service import points_by_transaction
from app.services.rule_service import (
    RuleServiceError,
    create_merchant_rule_from_transaction,
    learn_category,
    reapply_rules,
)
from app.services.transfer_detection_service import unpair_transfer
from app.services.transfer_marking import corrected_fields, release_from_transfer, settle_as_transfer

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


def _category_rule_read(rule: CategoryRule | None) -> CategoryRuleRead | None:
    if rule is None:
        return None
    return CategoryRuleRead(
        id=rule.id, pattern=rule.pattern, is_regex=rule.is_regex, match_field=rule.match_field,
        category=rule.category, priority=rule.priority, is_user_defined=rule.is_user_defined,
    )


def _to_read(t: Transaction, account_name: str) -> TransactionRead:
    source_filename = None
    if t.raw_transaction and t.raw_transaction.import_record:
        source_filename = t.raw_transaction.import_record.filename
    return TransactionRead(
        id=t.id,
        account_id=t.account_id,
        account_name=account_name,
        transaction_date=t.transaction_date,
        normalized_description=t.normalized_description,
        merchant=t.merchant,
        category=t.category,
        amount_minor=t.amount_minor,
        currency=t.currency,
        transaction_type=t.transaction_type,
        is_duplicate=t.is_duplicate,
        is_transfer=t.is_transfer,
        needs_review=t.needs_review,
        review_reason=review_reason_text(t.review_reason),
        notes=t.notes,
        source_filename=source_filename,
        country=t.country,
        city=t.city,
        online=t.online,
    )


TransactionSort = Literal["date", "amount", "account", "type"]
SortOrder = Literal["asc", "desc"]


def search_filter(search: str):
    """Description or merchant contains `search`. Umlauts and case don't
    matter ("BÄCKEREI" finds "Baeckerei", "Muller" finds "Müller"); LIKE
    wildcards are escaped so "50%" or "_" are searched literally."""
    def pattern(text: str) -> str:
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    like, plain = pattern(fold_text(search)), pattern(fold_plain(search))
    return (
        func.fold(Transaction.normalized_description).like(like, escape="\\")
        | func.fold(Transaction.merchant).like(like, escape="\\")
        | func.fold_plain(Transaction.normalized_description).like(plain, escape="\\")
        | func.fold_plain(Transaction.merchant).like(plain, escape="\\")
    )


def sorted_by(stmt, sort: TransactionSort, order: SortOrder):
    """The chosen column (an amount: signed, so the biggest expense is the
    smallest), then newest first — a stable order across pages."""
    column = {
        "date": Transaction.transaction_date,
        "amount": Transaction.amount_minor,
        "account": func.lower(Account.name),
        "type": Transaction.transaction_type,
    }[sort]
    if sort == "account":
        stmt = stmt.join(Account, Account.id == Transaction.account_id)
    return stmt.order_by(column.asc() if order == "asc" else column.desc(),
                         Transaction.transaction_date.desc(), Transaction.id.desc())


@router.get("", response_model=TransactionListResponse)
def list_transactions(
    account_id: int | None = None,
    category: str | None = None,
    merchant: str | None = None,
    transaction_type: TransactionType | None = None,
    start: date | None = None,
    end: date | None = None,
    search: str | None = None,
    include_duplicates: bool = False,
    include_transfers: bool = True,
    needs_review: bool | None = None,
    # as the reports count: archived accounts left out (unless an account is chosen)
    active_accounts_only: bool = False,
    sort: TransactionSort = "date",
    order: SortOrder = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    session: Session = Depends(get_session),
):
    stmt = select(Transaction)
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    if category is not None:
        stmt = stmt.where(Transaction.category == category)
    if merchant is not None:
        stmt = stmt.where(Transaction.merchant == merchant)
    if transaction_type is not None:
        stmt = stmt.where(Transaction.transaction_type == transaction_type)
    if start is not None:
        stmt = stmt.where(Transaction.transaction_date >= start)
    if end is not None:
        stmt = stmt.where(Transaction.transaction_date <= end)
    if not include_duplicates:
        stmt = stmt.where(Transaction.is_duplicate == False)  # noqa: E712
    if not include_transfers:
        stmt = stmt.where(Transaction.is_transfer == False)  # noqa: E712
    if needs_review is not None:
        stmt = stmt.where(Transaction.needs_review == needs_review)
    if active_accounts_only and account_id is None:
        stmt = stmt.where(Transaction.account_id.in_(
            select(Account.id).where(Account.is_archived == False)))  # noqa: E712
    if search:
        stmt = stmt.where(search_filter(search))

    # SQL-level count + pagination — never loads the full filtered result
    # set into memory (important once the table has 100,000+ rows).
    total = session.exec(select(func.count()).select_from(stmt.subquery())).one()

    paginated_stmt = (
        sorted_by(stmt, sort, order)
        .options(selectinload(Transaction.raw_transaction).selectinload(RawTransaction.import_record))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    page_items = session.exec(paginated_stmt).all()

    accounts_by_id = {a.id: a.name for a in session.exec(select(Account)).all()}

    items = [_to_read(t, accounts_by_id.get(t.account_id, "Unknown")) for t in page_items]
    points = points_by_transaction(session, [t.id for t in page_items])
    for item in items:
        item.points = points.get(item.id)
    if needs_review:
        # the review queue: suggest a category for the unsorted ones (the user confirms)
        suggestions = UnsortedSuggestions(session)
        for item, t in zip(items, page_items, strict=True):
            item.suggested_category = suggestions.for_transaction(t)

    return TransactionListResponse(items=items, total=total, page=page, page_size=page_size)


# A group of thousands of bookings is sent with the details of only the
# newest ones (the page shows a few); the rest go as ids.
MAX_GROUP_DETAILS = 200


@router.get("/review-groups", response_model=ReviewGroupsResponse)
def review_groups(
    page: int = Query(1, ge=1, le=10_000), page_size: int = Query(20, ge=1, le=200),
    session: Session = Depends(get_session),
):
    """The review queue grouped by payee, biggest groups first (app.services.review_service)."""
    result = review_service.review_groups(session, page, page_size)
    members = [t for g in result.groups for t in g.transactions[:MAX_GROUP_DETAILS]]
    accounts_by_id = {a.id: a.name for a in session.exec(select(Account)).all()}
    points = points_by_transaction(session, [t.id for t in members])
    groups = []
    for group in result.groups:
        items = [_to_read(t, accounts_by_id.get(t.account_id, "Unknown")) for t in group.transactions[:MAX_GROUP_DETAILS]]
        for item in items:
            item.points = points.get(item.id)
        groups.append(ReviewGroupRead(
            key=group.key, label=group.label, learnable=group.learnable, count=len(group.transactions),
            total_minor=group.total_minor, currency=group.transactions[0].currency,
            suggested_category=group.suggested_category, transactions=items,
            member_ids=[t.id for t in group.transactions],
        ))
    return ReviewGroupsResponse(groups=groups, total_groups=result.total_groups,
                                total_transactions=result.total_transactions, page=page, page_size=page_size)


@router.post("/assign-category", response_model=AssignCategoryResponse)
def assign_category(payload: AssignCategoryRequest, session: Session = Depends(get_session)):
    """One category for several transactions (a review group); with `learn`,
    a rule is learned from the first one's payee as well."""
    try:
        result = review_service.assign_category(session, payload.transaction_ids, payload.category,
                                                learn=payload.learn, leave_out=set(payload.leave_out))
    except review_service.UnknownTransactionError:
        raise HTTPException(status_code=404, detail=tr("Transaction not found")) from None
    return AssignCategoryResponse(updated=result.updated, rule=_category_rule_read(result.rule),
                                  applied_to=result.applied_to)


# Fields where an explicit null means "clear it" (for the others, null or
# absent both mean "leave unchanged").
_CLEARABLE_FIELDS = {"notes"}


@router.patch("/{transaction_id}", response_model=TransactionRead)
def update_transaction(
    transaction_id: int, payload: TransactionUpdate, session: Session = Depends(get_session)
):
    tx = session.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail=tr("Transaction not found"))

    statement_to_recompute = None
    for field, new_value in payload.model_dump(exclude_unset=True).items():
        if new_value is None and field not in _CLEARABLE_FIELDS:
            continue
        old_value = getattr(tx, field)
        if str(new_value) == str(old_value):
            continue
        session.add(UserCorrection(
            transaction_id=tx.id, field=field,
            old_value=str(old_value.value if hasattr(old_value, "value") else old_value)
            if old_value is not None else None,
            new_value=str(new_value.value if hasattr(new_value, "value") else new_value) if new_value is not None else "",
        ))
        setattr(tx, field, new_value)

        # A manual type correction is authoritative and must not leave any
        # automatic link half in place: the partner of an auto-detected
        # transfer pair is reverted too, and a credit-card payment is
        # unlinked from its statement (which goes back to pending).
        if field == "transaction_type":
            if tx.transfer_pair_id is not None:
                unpair_transfer(session, tx)
            if tx.settles_statement_id is not None:
                statement_to_recompute = tx.settles_statement_id
                tx.settles_statement_id = None
            was_transfer, tx.is_transfer = tx.is_transfer, new_value == TransactionType.TRANSFER
            session.flush()  # the correction above counts for the category decision below
            corrected = corrected_fields(session, [tx.id])
            if tx.is_transfer:
                settle_as_transfer(tx, corrected)
            elif was_transfer:
                release_from_transfer(session, tx, corrected)

        # A manual merchant/category correction resolves the reason it
        # was flagged for review in the first place.
        if field in ("merchant", "category"):
            tx.needs_review = False
            tx.review_reason = None

    tx.updated_at = utcnow()
    session.add(tx)
    session.commit()
    if statement_to_recompute is not None:
        reconcile_statement(session, statement_to_recompute)
    session.refresh(tx)

    account = session.get(Account, tx.account_id)
    return _to_read(tx, account.name if account else "Unknown")


@router.post("/reapply-rules", response_model=ReapplyRulesResponse)
def reapply_rules_route(session: Session = Depends(get_session)):
    """Re-run merchant and category rules over all existing transactions.
    Manually corrected fields are never changed."""
    result = reapply_rules(session)
    return ReapplyRulesResponse(
        transactions_checked=result.transactions_checked,
        merchants_changed=result.merchants_changed,
        categories_changed=result.categories_changed,
    )


@router.post("/{transaction_id}/merchant-rule", response_model=CreateRuleResponse)
def create_merchant_rule(
    transaction_id: int, payload: CreateMerchantRuleRequest, session: Session = Depends(get_session)
):
    """Confirms a merchant correction as a reusable rule (spec Milestone 3,
    section 3): future imports whose description matches the derived
    pattern will automatically normalize to this merchant. Also applies
    immediately to this transaction."""
    try:
        tx, rule, applied = create_merchant_rule_from_transaction(session, transaction_id, payload.normalized_merchant)
    except RuleServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    account = session.get(Account, tx.account_id)
    return CreateRuleResponse(
        transaction=_to_read(tx, account.name if account else "Unknown"),
        merchant_rule=MerchantRuleRead(
            id=rule.id, pattern=rule.pattern, is_regex=rule.is_regex,
            normalized_merchant=rule.normalized_merchant, is_user_defined=rule.is_user_defined,
        ),
        applied_to=applied,
    )


@router.post("/{transaction_id}/category-rule", response_model=CreateRuleResponse)
def create_category_rule(
    transaction_id: int, payload: CreateCategoryRuleRequest, session: Session = Depends(get_session)
):
    """Assigns a category and learns it (spec Milestone 3, section 4): a
    rule derived from the payee applies to this transaction, to similar
    existing ones (unless corrected by hand) and to future imports."""
    try:
        lesson = learn_category(session, transaction_id, payload.category)
    except RuleServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    tx, rule = lesson.transaction, lesson.rule
    account = session.get(Account, tx.account_id)
    return CreateRuleResponse(
        transaction=_to_read(tx, account.name if account else "Unknown"),
        category_rule=_category_rule_read(rule),
        applied_to=lesson.applied_to,
    )
