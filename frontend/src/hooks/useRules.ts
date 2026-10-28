import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createCategoryRule, createMerchantRule, forgetCategoryRule, listLearnedCategoryRules } from "../api/rules";
import { invalidateTransactionDependentQueries } from "./invalidation";

export function useCreateMerchantRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ transactionId, normalizedMerchant }: { transactionId: number; normalizedMerchant: string }) =>
      createMerchantRule(transactionId, normalizedMerchant),
    onSuccess: () => invalidateTransactionDependentQueries(qc),
  });
}

export function useCreateCategoryRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ transactionId, category }: { transactionId: number; category: string }) =>
      createCategoryRule(transactionId, category),
    onSuccess: () => invalidateTransactionDependentQueries(qc),
  });
}

export function useLearnedCategoryRules() {
  return useQuery({ queryKey: ["learned-category-rules"], queryFn: listLearnedCategoryRules });
}

export function useForgetCategoryRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ruleId: number) => forgetCategoryRule(ruleId),
    onSuccess: () => invalidateTransactionDependentQueries(qc),
  });
}
