import { apiGet, apiPatch, apiPost } from "./client";
import type { Account, AccountType, StatementReminder } from "../types";

export function listAccounts(includeArchived = false) {
  return apiGet<Account[]>("/api/accounts", { include_archived: includeArchived || undefined });
}

export function createAccount(input: { name: string; account_type: AccountType; currency?: string; iban?: string | null }) {
  return apiPost<Account>("/api/accounts", input);
}

export function updateAccount(
  id: number,
  patch: Partial<
    Pick<Account, "name" | "currency" | "iban" | "is_archived" | "opening_balance_minor" | "opening_balance_date">
  >
) {
  return apiPatch<Account>(`/api/accounts/${id}`, patch);
}

/** Statements that should be out by now but are not imported yet. */
export function listStatementReminders() {
  return apiGet<StatementReminder[]>("/api/accounts/statement-reminders");
}
