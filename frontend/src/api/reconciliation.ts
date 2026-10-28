import { apiGet, apiPost } from "./client";
import type { ReconciliationDetail } from "../types";

export function getReconciliationDetail(statementId: number) {
  return apiGet<ReconciliationDetail>(`/api/reconciliation/statements/${statementId}`);
}

export function selectBankPayment(statementId: number, transactionId: number) {
  return apiPost<ReconciliationDetail>(`/api/reconciliation/statements/${statementId}/select-bank-payment`, {
    transaction_id: transactionId,
  });
}

/** The linked payment is wrong: unlink it (it counts as a normal expense again). */
export function clearBankPayment(statementId: number) {
  return apiPost<ReconciliationDetail>(`/api/reconciliation/statements/${statementId}/clear-bank-payment`);
}

/** Re-run automatic matching (exact, unambiguous amount only). */
export function findBankPayment(statementId: number) {
  return apiPost<ReconciliationDetail>(`/api/reconciliation/statements/${statementId}/find-payment`);
}

export function resolveReconciliation(statementId: number, notes: string | null, tags: string[] | null) {
  return apiPost<ReconciliationDetail>(`/api/reconciliation/statements/${statementId}/resolve`, {
    notes,
    tags,
  });
}
