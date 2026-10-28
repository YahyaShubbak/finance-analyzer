import { useMutation, useQueryClient } from "@tanstack/react-query";
import { rerunTransferDetection } from "../api/transfers";
import { invalidateTransactionDependentQueries } from "./invalidation";

export function useRerunTransferDetection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: rerunTransferDetection,
    onSuccess: () => invalidateTransactionDependentQueries(qc),
  });
}
