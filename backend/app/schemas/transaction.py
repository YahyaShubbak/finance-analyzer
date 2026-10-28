from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import TransactionType


class TransactionRead(BaseModel):
    id: int
    account_id: int
    account_name: str
    transaction_date: date
    normalized_description: str
    merchant: str | None
    category: str | None
    amount_minor: int
    currency: str
    transaction_type: TransactionType
    is_duplicate: bool
    is_transfer: bool
    needs_review: bool
    review_reason: str | None
    notes: str | None
    source_filename: str | None = None
    # where it took place (app.normalization.location); all empty: unknown
    country: str | None = None
    city: str | None = None
    online: bool = False
    # for unsorted transactions in the review queue: what similar sorted ones are (to confirm)
    suggested_category: str | None = None
    # bonus points the booking earned, as its statement says (app/services/points_service.py)
    points: int | None = None

    model_config = ConfigDict(from_attributes=True)


class TransactionListResponse(BaseModel):
    items: list[TransactionRead]
    total: int
    page: int
    page_size: int


class TransactionUpdate(BaseModel):
    category: str | None = Field(default=None, min_length=1, max_length=100)
    merchant: str | None = Field(default=None, min_length=1, max_length=200)
    transaction_type: TransactionType | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ReapplyRulesResponse(BaseModel):
    transactions_checked: int
    merchants_changed: int
    categories_changed: int


class CreateMerchantRuleRequest(BaseModel):
    normalized_merchant: str = Field(min_length=1, max_length=200, pattern=r"\S")


class CreateCategoryRuleRequest(BaseModel):
    category: str = Field(min_length=1, max_length=80)


class MerchantRuleRead(BaseModel):
    id: int
    pattern: str
    is_regex: bool
    normalized_merchant: str
    is_user_defined: bool


class CategoryRuleRead(BaseModel):
    id: int
    pattern: str
    is_regex: bool
    match_field: str
    category: str
    priority: int
    is_user_defined: bool


class CreateRuleResponse(BaseModel):
    transaction: TransactionRead
    merchant_rule: MerchantRuleRead | None = None
    category_rule: CategoryRuleRead | None = None
    # other existing transactions the learned category rule was applied to
    applied_to: int = 0


class LearnedCategoryRuleRead(BaseModel):
    id: int
    pattern: str
    match_field: str
    category: str
    matching_transactions: int
    created_at: datetime


class ForgetRuleResponse(BaseModel):
    transactions_changed: int


class ReviewGroupRead(BaseModel):
    """Transactions to review that a learned category would cover together
    (the same payee, see rule_service.derive_category_pattern)."""
    key: str
    label: str
    learnable: bool  # a rule can be learned for them (False: a single booking without a usable payee)
    count: int
    total_minor: int
    currency: str
    suggested_category: str | None = None
    transactions: list[TransactionRead]  # the first MAX_GROUP_DETAILS members, newest first
    member_ids: list[int]  # every member, for assigning the whole group


class ReviewGroupsResponse(BaseModel):
    groups: list[ReviewGroupRead]
    total_groups: int
    total_transactions: int
    page: int
    page_size: int


class AssignCategoryRequest(BaseModel):
    transaction_ids: list[int] = Field(min_length=1, max_length=5000)
    category: str = Field(min_length=1, max_length=80)
    # also learn a rule from the payee (applies to similar and future bookings)
    learn: bool = False
    # bookings of the group the user left out: the learned rule doesn't sort them now
    leave_out: list[int] = Field(default_factory=list, max_length=5000)


class AssignCategoryResponse(BaseModel):
    updated: int
    rule: CategoryRuleRead | None = None
    applied_to: int = 0  # other existing bookings the learned rule changed
