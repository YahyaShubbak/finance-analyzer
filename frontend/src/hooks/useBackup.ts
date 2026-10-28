import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createBackup, listBackups, restoreFromExisting, restoreFromUpload } from "../api/backup";
import { invalidateTransactionDependentQueries } from "./invalidation";

export function useBackups() {
  return useQuery({ queryKey: ["backups"], queryFn: listBackups });
}

export function useCreateBackup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createBackup,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["backups"] }),
  });
}


export function useRestoreFromUpload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => restoreFromUpload(file),
    onSuccess: () => invalidateTransactionDependentQueries(qc),
  });
}

export function useRestoreFromExisting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (filename: string) => restoreFromExisting(filename),
    onSuccess: () => invalidateTransactionDependentQueries(qc),
  });
}
