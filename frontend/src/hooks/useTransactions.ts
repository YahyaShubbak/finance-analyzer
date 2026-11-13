import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { assignCategory, listReviewGroups, listTransactions, updateTransaction } from "../api/transactions";
import { invalidateTransactionDependentQueries } from "./invalidation";
import type { Transaction, TransactionFilters } from "../types";

export function useTransactions(filters: TransactionFilters) {
  return useQuery({
    queryKey: ["transactions", filters],
    queryFn: ({ signal }) => listTransactions(filters, signal),
    placeholderData: (prev) => prev,
  });
}

export function useUpdateTransaction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Partial<Transaction> }) =>
      updateTransaction(id, patch),
    onSuccess: () => invalidateTransactionDependentQueries(qc),
  });
}

export function useReviewGroups(page: number) {
  return useQuery({ queryKey: ["review-groups", page], queryFn: () => listReviewGroups(page) });
}

export function useAssignCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ ids, category, learn, leaveOut }: { ids: number[]; category: string; learn: boolean; leaveOut: number[] }) =>
      assignCategory(ids, category, learn, leaveOut),
    onSuccess: () => invalidateTransactionDependentQueries(qc),
  });
}
