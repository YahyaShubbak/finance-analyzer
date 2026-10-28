import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  clearBankPayment,
  findBankPayment,
  getReconciliationDetail,
  resolveReconciliation,
  selectBankPayment,
} from "../api/reconciliation";
import { invalidateTransactionDependentQueries } from "./invalidation";

export function useReconciliationDetail(statementId: number | undefined) {
  return useQuery({
    queryKey: ["reconciliation", statementId],
    queryFn: () => getReconciliationDetail(statementId as number),
    enabled: statementId !== undefined,
  });
}

// Linking/unlinking a payment changes whether it counts as an expense, so
// every total must refresh.
export function useSelectBankPayment(statementId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (transactionId: number) => selectBankPayment(statementId, transactionId),
    onSuccess: () => invalidateTransactionDependentQueries(qc),
  });
}

export function useClearBankPayment(statementId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => clearBankPayment(statementId),
    onSuccess: () => invalidateTransactionDependentQueries(qc),
  });
}

export function useFindBankPayment(statementId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => findBankPayment(statementId),
    onSuccess: () => invalidateTransactionDependentQueries(qc),
  });
}

export function useResolveReconciliation(statementId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ notes, tags }: { notes: string | null; tags: string[] | null }) =>
      resolveReconciliation(statementId, notes, tags),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["reconciliation", statementId] }),
  });
}
