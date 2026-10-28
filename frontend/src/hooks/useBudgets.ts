import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteBudget, getBudgetStatus, listBudgets, upsertBudget } from "../api/budgets";

export function useBudgets() {
  return useQuery({ queryKey: ["budgets"], queryFn: listBudgets });
}

export function useBudgetStatus(month: string) {
  return useQuery({ queryKey: ["budget-status", month], queryFn: () => getBudgetStatus(month) });
}

export function useUpsertBudget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ category, amountMinor, currency }: { category: string; amountMinor: number; currency?: string }) =>
      upsertBudget(category, amountMinor, currency),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["budgets"] });
      qc.invalidateQueries({ queryKey: ["budget-status"] });
    },
  });
}

export function useDeleteBudget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteBudget(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["budgets"] });
      qc.invalidateQueries({ queryKey: ["budget-status"] });
    },
  });
}
