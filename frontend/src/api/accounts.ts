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

export interface Wallet {
  withdrawn_minor: number;
  entries_minor: number;
  balance_minor: number;
}

export function getWallet(accountId: number) {
  return apiGet<Wallet>(`/api/accounts/${accountId}/wallet`);
}

/** amountMinor: negative paid out, positive taken in. */
export function addCashEntry(accountId: number, entry: { transaction_date: string; amount_minor: number; category: string; note?: string }) {
  return apiPost<Wallet>(`/api/accounts/${accountId}/cash-entries`, entry);
}

export function countCash(accountId: number, counted: { counted_on: string; counted_minor: number }) {
  return apiPost<Wallet>(`/api/accounts/${accountId}/cash-count`, counted);
}
