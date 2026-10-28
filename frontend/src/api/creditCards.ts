import { apiGet } from "./client";
import type { CreditCardSummary, StatementSummary } from "../types";

export function listCreditCards() {
  return apiGet<CreditCardSummary[]>("/api/credit-cards");
}

export function listStatements(accountId: number) {
  return apiGet<StatementSummary[]>(`/api/credit-cards/${accountId}/statements`);
}
