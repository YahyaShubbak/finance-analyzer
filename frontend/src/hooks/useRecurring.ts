import { useQuery } from "@tanstack/react-query";
import { getForecast, getRecurringSeries } from "../api/recurring";

export function useRecurringSeries(accountId?: string) {
  return useQuery({ queryKey: ["recurring-series", accountId], queryFn: () => getRecurringSeries(accountId) });
}

export function useForecast(months = 3, accountId?: string) {
  return useQuery({ queryKey: ["forecast", months, accountId], queryFn: () => getForecast(months, accountId) });
}
