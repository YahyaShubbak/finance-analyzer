"""The frontend repeats by hand what the backend defines: the built-in
categories, the values of its enums, the fields of what the API returns
(frontend/src/lib/categories.ts, frontend/src/types/index.ts). Nothing
generates one from the other — so these tests read the TypeScript files
and fail when the two sides have drifted apart.

A frontend type may leave out fields it has no use for; it must not expect
one the backend does not send.
"""
from __future__ import annotations

import re
import typing
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.api.routes.categories import CategoryRead
from app.api.routes.system import SystemInfo
from app.api.transaction_listing import SortOrder, TransactionSort
from app.db.models import AccountType, DocumentType, ReconciliationStatus, TransactionType
from app.importers.column_detection import LOGICAL_FIELDS
from app.normalization.category import BUILT_IN_CATEGORIES
from app.schemas import account, analytics, backup, budget, credit_card, imports, points, transaction

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
pytestmark = pytest.mark.skipif(not FRONTEND.is_dir(), reason="the frontend's sources are not here")


def _types() -> str:
    return (FRONTEND / "types" / "index.ts").read_text(encoding="utf-8")


def _union(name: str) -> set[str]:
    """export type Name = "a" | "b";  ->  {"a", "b"}"""
    match = re.search(rf"export type {name} =([^;]+);", _types())
    assert match, f"type {name} not found in types/index.ts"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def _fields(name: str) -> set[str]:
    """The field names of `export interface Name { ... }` (not of nested object types)."""
    match = re.search(rf"export interface {name}(?: extends \w+)? \{{\n(.*?)\n\}}", _types(), re.DOTALL)
    assert match, f"interface {name} not found in types/index.ts"
    return set(re.findall(r"^  (\w+)\??:", match.group(1), re.MULTILINE))


def test_the_built_in_categories_are_the_same_on_both_sides():
    source = (FRONTEND / "lib" / "categories.ts").read_text(encoding="utf-8")
    listed = re.search(r"export const CATEGORIES = \[(.*?)\];", source, re.DOTALL)
    assert listed
    assert tuple(re.findall(r'"([^"]+)"', listed.group(1))) == BUILT_IN_CATEGORIES


@pytest.mark.parametrize("language", ["en", "de"])
def test_every_built_in_category_has_its_name_in_the_interface(language):
    texts = (FRONTEND / "i18n" / f"{language}.ts").read_text(encoding="utf-8")
    missing = [name for name in BUILT_IN_CATEGORIES if f'"category.{name}":' not in texts]
    assert missing == []


@pytest.mark.parametrize(("type_name", "values"), [
    ("AccountType", {member.value for member in AccountType}),
    ("DocumentType", {member.value for member in DocumentType}),
    ("TransactionType", {member.value for member in TransactionType}),
    ("ReconciliationStatus", {member.value for member in ReconciliationStatus}),
    ("TransactionSortKey", set(typing.get_args(TransactionSort))),
])
def test_a_type_of_fixed_values_lists_what_the_backend_knows(type_name, values):
    assert _union(type_name) == values


def test_the_column_dialog_offers_only_fields_the_readers_know():
    """(Not all of them: some are only ever found by the readers themselves.)"""
    assert _union("MappableField") <= set(LOGICAL_FIELDS)


def test_the_order_of_a_list_is_asc_or_desc_on_both_sides():
    order = re.search(r"export interface TransactionSort \{.*?order: ([^;]+);", _types(), re.DOTALL)
    assert order and set(re.findall(r'"([^"]+)"', order.group(1))) == set(typing.get_args(SortOrder))


@pytest.mark.parametrize(("interface", "schema"), [
    ("Account", account.AccountRead),
    ("Transaction", transaction.TransactionRead),
    ("TransactionListResponse", transaction.TransactionListResponse),
    ("LearnedCategoryRule", transaction.LearnedCategoryRuleRead),
    ("ReviewGroup", transaction.ReviewGroupRead),
    ("ImportIssue", imports.ImportIssueRead),
    ("ParsedTransactionPreview", imports.ParsedTransactionRead),
    ("DuplicateMatch", imports.DuplicateMatchRead),
    ("RowClassification", imports.RowClassificationRead),
    ("ParseOptions", imports.ParseOptionsIn),
    ("PdfTemplate", imports.PdfTemplateIn),
    ("TotalCheck", imports.TotalCheckRead),
    ("ImportPreview", imports.ImportPreviewResponse),
    ("ImportCommitResult", imports.ImportCommitResponse),
    ("ImportRecord", imports.ImportRecordRead),
    ("CurrencyTotals", analytics.CurrencyTotals),
    ("Totals", analytics.TotalsResponse),
    ("CategoryBreakdownItem", analytics.CategoryBreakdownItem),
    ("LocationBreakdownItem", analytics.LocationBreakdownItem),
    ("MonthlyPoint", analytics.MonthlyPoint),
    ("AccountBreakdownItem", analytics.AccountBreakdownItem),
    ("TransfersSummary", analytics.TransfersSummaryResponse),
    ("StatementSummary", credit_card.StatementSummary),
    ("CreditCardSummary", credit_card.CreditCardSummary),
    ("Budget", budget.BudgetRead),
    ("BudgetStatusItem", budget.BudgetStatusItem),
    ("BudgetStatusResponse", budget.BudgetStatusResponse),
    ("BackupInfo", backup.BackupInfoRead),
    ("RestoreResult", backup.RestoreResultRead),
    ("PointsMonth", points.PointsMonth),
    ("PointsProgram", points.PointsProgramSummary),
    ("SystemInfo", SystemInfo),
    ("CategoryInfo", CategoryRead),
])
def test_the_frontend_expects_no_field_the_backend_does_not_send(interface: str, schema: type[BaseModel]):
    unknown = _fields(interface) - set(schema.model_fields)
    assert unknown == set(), f"{interface} (types/index.ts) has fields {schema.__name__} lacks"
