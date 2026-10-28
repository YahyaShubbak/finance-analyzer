"""Rules the app learned from the user's category assignments."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.transaction import ForgetRuleResponse, LearnedCategoryRuleRead
from app.services.rule_service import RuleServiceError, forget_category_rule, list_learned_category_rules

router = APIRouter(prefix="/api/rules", tags=["rules"])


@router.get("/category", response_model=list[LearnedCategoryRuleRead])
def learned_category_rules(session: Session = Depends(get_session)):
    return [
        LearnedCategoryRuleRead(
            id=item.rule.id, pattern=item.rule.pattern, match_field=item.rule.match_field,
            category=item.rule.category, matching_transactions=item.matching_transactions,
            created_at=item.rule.created_at,
        )
        for item in list_learned_category_rules(session)
    ]


@router.delete("/category/{rule_id}", response_model=ForgetRuleResponse)
def forget_learned_category_rule(rule_id: int, session: Session = Depends(get_session)):
    """Forget a learned rule. Transactions it categorized fall back to what
    the remaining rules say; categories set by hand stay."""
    try:
        changed = forget_category_rule(session, rule_id)
    except RuleServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ForgetRuleResponse(transactions_changed=changed)
