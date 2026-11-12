import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  commitImport,
  discardStagedImport,
  listImports,
  previewImport,
  removeImport,
  removeImports,
  recognizeImport,
  reparseImport,
} from "../api/imports";
import { invalidateTransactionDependentQueries } from "./invalidation";
import type { ParseOptions, RowDecision } from "../types";

export function useImportHistory() {
  return useQuery({ queryKey: ["imports"], queryFn: listImports });
}

export function usePreviewImport() {
  return useMutation({
    mutationFn: ({ file, accountId }: { file: File; accountId?: number }) => previewImport(file, accountId),
  });
}

export function useReparseImport() {
  return useMutation({
    mutationFn: ({ stagingId, accountId, options }: { stagingId: string; accountId: number | null; options: ParseOptions }) =>
      reparseImport(stagingId, accountId, options),
  });
}

export function useRecognizeImport() {
  return useMutation({ mutationFn: (stagingId: string) => recognizeImport(stagingId) });
}

export function useDiscardStagedImport() {
  return useMutation({ mutationFn: (stagingId: string) => discardStagedImport(stagingId) });
}

export function useCommitImport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      stagingId,
      accountId,
      rowDecisions,
      auto,
      verified,
    }: {
      stagingId: string;
      accountId: number;
      rowDecisions?: RowDecision[];
      auto?: boolean;
      verified?: boolean;
    }) => commitImport(stagingId, accountId, rowDecisions, auto, verified),
    // Not awaited (nothing returned): the import is done when the server says so, not when
    // every list on the page was loaded again — with many files, each waited for all of that.
    onSuccess: () => {
      void invalidateTransactionDependentQueries(qc);
    },
  });
}

export function useRemoveImports() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (importIds: number[]) => removeImports(importIds),
    onSuccess: () => invalidateTransactionDependentQueries(qc),
  });
}

export function useRemoveImport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (importId: number) => removeImport(importId),
    onSuccess: () => invalidateTransactionDependentQueries(qc),
  });
}
