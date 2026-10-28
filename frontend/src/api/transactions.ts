import { apiGet, apiPatch, apiPost } from "./client";
import type {
  AssignCategoryResult,
  ReapplyRulesResult,
  ReviewGroupsResponse,
  Transaction,
  TransactionFilters,
  TransactionListResponse,
} from "../types";

export function listTransactions(filters: TransactionFilters) {
  return apiGet<TransactionListResponse>("/api/transactions", {
    account_id: filters.account_id,
    category: filters.category,
    merchant: filters.merchant,
    transaction_type: filters.transaction_type,
    start: filters.start,
    end: filters.end,
    search: filters.search,
    include_transfers: filters.include_transfers,
    needs_review: filters.needs_review,
    active_accounts_only: filters.active_accounts_only,
    sort: filters.sort,
    order: filters.order,
    page: filters.page ?? 1,
    page_size: filters.page_size ?? 50,
  });
}

export function updateTransaction(
  id: number,
  patch: Partial<Pick<Transaction, "category" | "merchant" | "transaction_type" | "notes">>
) {
  return apiPatch<Transaction>(`/api/transactions/${id}`, patch);
}

/** Re-run merchant/category rules over all transactions (manual corrections are kept). */
export function reapplyRules() {
  return apiPost<ReapplyRulesResult>("/api/transactions/reapply-rules");
}

/** The review queue grouped by payee, biggest groups first. */
export function listReviewGroups(page: number, pageSize = 20) {
  return apiGet<ReviewGroupsResponse>("/api/transactions/review-groups", { page, page_size: pageSize });
}

/** One category for several transactions; `learn`: also as a rule from the first one's payee. */
export function assignCategory(transactionIds: number[], category: string, learn: boolean, leaveOut: number[] = []) {
  return apiPost<AssignCategoryResult>("/api/transactions/assign-category", {
    transaction_ids: transactionIds,
    category,
    learn,
    leave_out: leaveOut,
  });
}
