import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getSystemInfo, resetEverything } from "../api/system";
import { reapplyRules } from "../api/transactions";
import { invalidateTransactionDependentQueries } from "./invalidation";

export function useSystemInfo() {
  return useQuery({ queryKey: ["system-info"], queryFn: getSystemInfo, staleTime: Infinity });
}

/** Checked now and then: an update on disk needs a restart of the running program.
 * (The same cache entry as useSystemInfo: one request serves both.) */
export function useRestartNeeded(): boolean {
  const { data } = useQuery({
    queryKey: ["system-info"],
    queryFn: getSystemInfo,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });
  return Boolean(data?.restart_needed);
}

export function useReapplyRules() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: reapplyRules, onSuccess: () => invalidateTransactionDependentQueries(qc) });
}

export function useResetEverything() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (deleteBackups: boolean) => resetEverything(deleteBackups),
    onSuccess: () => qc.invalidateQueries(),
  });
}
