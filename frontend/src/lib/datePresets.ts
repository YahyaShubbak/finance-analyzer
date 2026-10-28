import { toLocalIsoDate } from "./format";

export interface DateRange {
  start: string | undefined;
  end: string | undefined;
}

export type DatePreset = "This month" | "Last 3 months" | "Year to date" | "All time";

/** Preset ranges relative to `now`, in LOCAL dates (toISOString() would
 * use UTC and start "This month" on the last day of the previous month
 * anywhere east of Greenwich). */
export function datePresets(now: Date = new Date()): Record<DatePreset, DateRange> {
  const startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
  const startOf3MonthsAgo = new Date(now.getFullYear(), now.getMonth() - 2, 1);
  const startOfYear = new Date(now.getFullYear(), 0, 1);
  return {
    "This month": { start: toLocalIsoDate(startOfMonth), end: toLocalIsoDate(now) },
    "Last 3 months": { start: toLocalIsoDate(startOf3MonthsAgo), end: toLocalIsoDate(now) },
    "Year to date": { start: toLocalIsoDate(startOfYear), end: toLocalIsoDate(now) },
    "All time": { start: undefined, end: undefined },
  };
}

export function matchingPreset(range: DateRange): DatePreset | undefined {
  return (Object.entries(datePresets()) as [DatePreset, DateRange][]).find(
    ([, value]) => value.start === range.start && value.end === range.end
  )?.[0];
}
