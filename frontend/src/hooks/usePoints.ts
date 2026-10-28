import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listPoints, updatePointsProgram } from "../api/points";

export function usePoints() {
  return useQuery({ queryKey: ["points"], queryFn: listPoints });
}

export function useUpdatePointsProgram() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...changes }: { id: number; name?: string; value_per_100?: number }) => updatePointsProgram(id, changes),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["points"] }),
  });
}
