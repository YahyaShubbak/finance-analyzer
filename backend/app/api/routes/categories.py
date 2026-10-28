"""Built-in and user-created categories."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from app.db.session import get_session
from app.services.category_service import (
    CategoryConflict,
    CategoryError,
    CategoryNotFound,
    create_category,
    delete_category,
    list_categories,
    rename_category,
)

router = APIRouter(prefix="/api/categories", tags=["categories"])


class CategoryRead(BaseModel):
    name: str
    built_in: bool
    id: int | None
    transaction_count: int


class CategoryWrite(BaseModel):
    name: str


class CategoryDeleted(BaseModel):
    transactions_moved: int


def _http(exc: CategoryError) -> HTTPException:
    status = 404 if isinstance(exc, CategoryNotFound) else 409 if isinstance(exc, CategoryConflict) else 422
    return HTTPException(status_code=status, detail=str(exc))


@router.get("", response_model=list[CategoryRead])
def categories(session: Session = Depends(get_session)):
    return [CategoryRead(**vars(c)) for c in list_categories(session)]


@router.post("", response_model=CategoryRead)
def add_category(payload: CategoryWrite, session: Session = Depends(get_session)):
    try:
        category = create_category(session, payload.name)
    except CategoryError as exc:
        raise _http(exc) from exc
    return CategoryRead(name=category.name, built_in=False, id=category.id, transaction_count=0)


@router.patch("/{category_id}", response_model=CategoryRead)
def change_category(category_id: int, payload: CategoryWrite, session: Session = Depends(get_session)):
    try:
        category = rename_category(session, category_id, payload.name)
    except CategoryError as exc:
        raise _http(exc) from exc
    count = next((c.transaction_count for c in list_categories(session) if c.id == category.id), 0)
    return CategoryRead(name=category.name, built_in=False, id=category.id, transaction_count=count)


@router.delete("/{category_id}", response_model=CategoryDeleted)
def remove_category(
    category_id: int,
    replacement: str | None = Query(None, description="category for its transactions; none: 'Other …' + review"),
    session: Session = Depends(get_session),
):
    try:
        moved = delete_category(session, category_id, replacement)
    except CategoryError as exc:
        raise _http(exc) from exc
    return CategoryDeleted(transactions_moved=moved)
