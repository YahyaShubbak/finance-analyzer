import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { createBackup, listBackups, restoreFromExisting, restoreFromUpload } from "../api/backup";
import { invalidateTransactionDependentQueries } from "./invalidation";
import { clearQueue } from "../state/importQueue";

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

/** The restored backup replaced every import: the cards of files imported
 * before refer to imports that are gone — or, worse, to other imports that
 * have their numbers now ("Undo" would remove those). */
function afterRestore(qc: QueryClient) {
  clearQueue();
  return invalidateTransactionDependentQueries(qc);
}

export function useRestoreFromUpload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => restoreFromUpload(file),
    onSuccess: () => afterRestore(qc),
  });
}

export function useRestoreFromExisting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (filename: string) => restoreFromExisting(filename),
    onSuccess: () => afterRestore(qc),
  });
}
