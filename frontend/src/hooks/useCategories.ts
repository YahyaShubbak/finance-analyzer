import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createCategory, deleteCategory, listCategories, renameCategory } from "../api/categories";
import { CATEGORIES } from "../lib/categories";
import { invalidateTransactionDependentQueries } from "./invalidation";

export function useCategories() {
  return useQuery({ queryKey: ["categories"], queryFn: listCategories });
}

/** Every category to choose from: the built-in ones, then the user's own. */
export function useCategoryNames(): string[] {
  const { data } = useCategories();
  const custom = (data ?? []).filter((c) => !c.built_in).map((c) => c.name);
  return [...CATEGORIES, ...custom];
}

export function useCreateCategory() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (name: string) => createCategory(name), onSuccess: () => invalidateTransactionDependentQueries(qc) });
}

export function useRenameCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) => renameCategory(id, name),
    onSuccess: () => invalidateTransactionDependentQueries(qc),
  });
}

export function useDeleteCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, replacement }: { id: number; replacement: string | null }) => deleteCategory(id, replacement),
    onSuccess: () => invalidateTransactionDependentQueries(qc),
  });
}
