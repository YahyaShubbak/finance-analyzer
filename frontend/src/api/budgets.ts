import { apiDelete, apiGet, apiPut } from "./client";
import type { Budget, BudgetStatusResponse } from "../types";

export function listBudgets() {
  return apiGet<Budget[]>("/api/budgets");
}

export function upsertBudget(category: string, amountMinor: number, currency = "EUR") {
  return apiPut<Budget>(`/api/budgets/${encodeURIComponent(category)}`, {
    amount_minor: amountMinor,
    currency,
  });
}

export function deleteBudget(id: number) {
  return apiDelete<void>(`/api/budgets/${id}`);
}

export function getBudgetStatus(month: string) {
  return apiGet<BudgetStatusResponse>("/api/budgets/status", { month });
}
