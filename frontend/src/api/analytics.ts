import { apiGet } from "./client";
import type {
  TransactionSortKey,
  AccountBreakdownItem,
  CategoryBreakdownItem,
  CategoryTransactions,
  LocationBreakdownItem,
  MonthlyPoint,
  TransfersSummary,
  Totals,
} from "../types";

export interface AnalyticsQuery {
  account_id?: string; // comma-separated ids
  start?: string;
  end?: string;
  [key: string]: string | undefined;
}

export function getTotals(q: AnalyticsQuery) {
  return apiGet<Totals>("/api/analytics/totals", q);
}

export function getCategoryBreakdown(q: AnalyticsQuery) {
  return apiGet<CategoryBreakdownItem[]>("/api/analytics/by-category", q);
}

/** Search and order of a breakdown's transaction list. */
export interface ListView {
  search?: string;
  sort?: TransactionSortKey;
  order?: "asc" | "desc";
}

export interface CategoryTransactionsQuery extends ListView {
  category: string;
  currency: string;
  account_id?: string;
  start?: string;
  end?: string;
  page: number;
  page_size: number;
}

/** The transactions behind one category of getCategoryBreakdown — they add up to its amount. */
export function getCategoryTransactions(q: CategoryTransactionsQuery) {
  return apiGet<CategoryTransactions>("/api/analytics/by-category/transactions", { ...q });
}

export function getMonthlySeries(q: AnalyticsQuery) {
  return apiGet<MonthlyPoint[]>("/api/analytics/over-time", q);
}

export function getAccountBreakdown(q: AnalyticsQuery) {
  return apiGet<AccountBreakdownItem[]>("/api/analytics/by-account", q);
}


export function getTransfersSummary(q: AnalyticsQuery) {
  return apiGet<TransfersSummary>("/api/analytics/transfers-summary", q);
}

export function getLocationBreakdown(q: AnalyticsQuery) {
  return apiGet<LocationBreakdownItem[]>("/api/analytics/by-location", q);
}

/** One place of getLocationBreakdown: online purchases; a country (one town of it,
 * or those without a town); or, with neither, the ones with no known place. */
export interface LocationTransactionsQuery extends ListView {
  currency: string;
  country?: string;
  city?: string;
  no_city?: boolean;
  online?: boolean;
  start?: string;
  end?: string;
  page: number;
  page_size: number;
}

export function getLocationTransactions(q: LocationTransactionsQuery) {
  return apiGet<CategoryTransactions>("/api/analytics/by-location/transactions", { ...q });
}
