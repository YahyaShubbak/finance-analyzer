import { apiGet } from "./client";
import type { ForecastResponse, RecurringSeriesResponse } from "../types";

export function getRecurringSeries(accountId?: string) {
  return apiGet<RecurringSeriesResponse>("/api/recurring/series", { account_id: accountId });
}

export function getForecast(months = 3, accountId?: string) {
  return apiGet<ForecastResponse>("/api/recurring/forecast", { months, account_id: accountId });
}
