// The billing period of an import, as the months it is about: those its
// period covers by at least MIN_DAYS days. A statement from 2 May to 1 June
// is about May; one from 16 June to 15 July about June and July.
import { getFormatLocale } from "./format";

const MIN_DAYS = 5;
const DAY = 24 * 60 * 60 * 1000;

const parse = (iso: string) => new Date(iso.slice(0, 10) + "T00:00:00");
const monthKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;

/** The months ("YYYY-MM", oldest first) a period is about; [] without dates. */
export function billingMonths(start: string | null, end: string | null): string[] {
  if (!start && !end) return [];
  const from = parse(start ?? end!), to = parse(end ?? start!);
  if (to < from) return [monthKey(to)];
  const months: string[] = [];
  for (let first = new Date(from.getFullYear(), from.getMonth(), 1); first <= to; first.setMonth(first.getMonth() + 1)) {
    const next = new Date(first.getFullYear(), first.getMonth() + 1, 1);
    const covered = (Math.min(next.getTime(), to.getTime() + DAY) - Math.max(first.getTime(), from.getTime())) / DAY;
    if (Math.round(covered) >= MIN_DAYS) months.push(monthKey(first));
  }
  return months.length > 0 ? months : [monthKey(to)];
}

function monthName(month: string, withYear: boolean): string {
  const [year, m] = month.split("-").map(Number);
  return new Intl.DateTimeFormat(getFormatLocale(), withYear ? { month: "long", year: "numeric" } : { month: "long" })
    .format(new Date(year, m - 1, 1));
}

/** "July 2026", "June – July 2026", "December 2025 – January 2026". */
export function formatBillingPeriod(months: string[]): string {
  if (months.length === 0) return "";
  const first = months[0], last = months[months.length - 1];
  if (first === last) return monthName(first, true);
  return `${monthName(first, first.slice(0, 4) !== last.slice(0, 4))} – ${monthName(last, true)}`;
}

export const formatMonthLong = (month: string) => monthName(month, true);
