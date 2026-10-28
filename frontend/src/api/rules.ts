import { apiDelete, apiGet, apiPost } from "./client";
import type { CreateRuleResult, LearnedCategoryRule } from "../types";

export function createMerchantRule(transactionId: number, normalizedMerchant: string) {
  return apiPost<CreateRuleResult>(`/api/transactions/${transactionId}/merchant-rule`, {
    normalized_merchant: normalizedMerchant,
  });
}

/** Assigns the category and learns it for similar transactions (existing and future). */
export function createCategoryRule(transactionId: number, category: string) {
  return apiPost<CreateRuleResult>(`/api/transactions/${transactionId}/category-rule`, {
    category,
  });
}

export function listLearnedCategoryRules() {
  return apiGet<LearnedCategoryRule[]>("/api/rules/category");
}

export function forgetCategoryRule(ruleId: number) {
  return apiDelete<{ transactions_changed: number }>(`/api/rules/category/${ruleId}`);
}
