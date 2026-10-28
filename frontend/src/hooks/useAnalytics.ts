import { useQuery } from "@tanstack/react-query";
import {
  getAccountBreakdown,
  getCategoryBreakdown,
  getLocationBreakdown,
  getMonthlySeries,
  getTotals,
  getTransfersSummary,
  type AnalyticsQuery,
} from "../api/analytics";

export function useTotals(q: AnalyticsQuery) {
  return useQuery({ queryKey: ["totals", q], queryFn: () => getTotals(q) });
}

export function useCategoryBreakdown(q: AnalyticsQuery) {
  return useQuery({ queryKey: ["category-breakdown", q], queryFn: () => getCategoryBreakdown(q) });
}

export function useMonthlySeries(q: AnalyticsQuery) {
  return useQuery({ queryKey: ["monthly-series", q], queryFn: () => getMonthlySeries(q) });
}

export function useAccountBreakdown(q: AnalyticsQuery) {
  return useQuery({ queryKey: ["account-breakdown", q], queryFn: () => getAccountBreakdown(q) });
}

export function useTransfersSummary(q: AnalyticsQuery) {
  return useQuery({ queryKey: ["transfers-summary", q], queryFn: () => getTransfersSummary(q) });
}

export function useLocationBreakdown(q: AnalyticsQuery) {
  return useQuery({ queryKey: ["location-breakdown", q], queryFn: () => getLocationBreakdown(q) });
}
