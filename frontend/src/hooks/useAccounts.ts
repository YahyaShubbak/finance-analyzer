import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createAccount, listAccounts, updateAccount } from "../api/accounts";
import { invalidateTransactionDependentQueries } from "./invalidation";
import type { Account, AccountType } from "../types";

export function useAccounts(includeArchived = false) {
  return useQuery({ queryKey: ["accounts", { includeArchived }], queryFn: () => listAccounts(includeArchived) });
}

export function useCreateAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; account_type: AccountType; currency?: string; iban?: string | null }) =>
      createAccount(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }),
  });
}

export function useUpdateAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      patch,
    }: {
      id: number;
      patch: Partial<
        Pick<Account, "name" | "currency" | "iban" | "is_archived" | "opening_balance_minor" | "opening_balance_date">
      >;
    }) => updateAccount(id, patch),
    // Archiving or an opening balance changes dashboard/report figures too.
    onSuccess: () => invalidateTransactionDependentQueries(qc),
  });
}
