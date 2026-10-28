import type { QueryClient } from "@tanstack/react-query";

/**
 * Any mutation that can change a transaction's category, merchant, type,
 * transfer/payment link or existence affects almost every figure in the
 * app (balances, totals, budgets, forecasts, reconciliation). Rather than
 * maintaining an itemized list of query keys — which drifted out of date
 * before — the whole cache is invalidated. Only queries of the currently
 * visible page actually refetch, so this is cheap.
 */
export function invalidateTransactionDependentQueries(qc: QueryClient) {
  return qc.invalidateQueries();
}
