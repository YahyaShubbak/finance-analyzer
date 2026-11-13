import { LOCALES, getLang, type MessageKey } from "../i18n/core";

// The chosen language's locale (German by default), switched by the
// LanguageProvider. Kept here, not in React state, so plain functions
// (chart tooltips, formatters) follow it too.
let locale = LOCALES[getLang()];

export function setFormatLocale(next: string) {
  if (next !== locale) {
    locale = next;
    moneyFormatters.clear();
  }
}

export function getFormatLocale(): string {
  return locale;
}

const moneyFormatters = new Map<string, Intl.NumberFormat | null>();

function moneyFormatter(currency: string): Intl.NumberFormat | null {
  if (!moneyFormatters.has(currency)) {
    try {
      moneyFormatters.set(currency, new Intl.NumberFormat(locale, { style: "currency", currency }));
    } catch {
      // Not an ISO 4217 code (e.g. "€" from an old import) — Intl throws a
      // RangeError, which must never take down the page.
      moneyFormatters.set(currency, null);
    }
  }
  return moneyFormatters.get(currency) ?? null;
}

export function formatMoney(minorUnits: number, currency = "EUR"): string {
  const value = minorUnits / 100;
  const formatter = moneyFormatter(currency);
  if (formatter) return formatter.format(value);
  const number = new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
  return `${number} ${currency}`.trim();
}

/** "€", "CHF", "$" — how the currency is written in amounts. */
export function currencySymbol(currency: string): string {
  try {
    const parts = new Intl.NumberFormat(locale, { style: "currency", currency }).formatToParts(0);
    return parts.find((part) => part.type === "currency")?.value ?? currency;
  } catch {
    return currency; // not an ISO code Intl knows
  }
}

export function formatSignedMoney(minorUnits: number, currency = "EUR"): string {
  const formatted = formatMoney(Math.abs(minorUnits), currency);
  return minorUnits < 0 ? `-${formatted}` : `+${formatted}`;
}

/** "YYYY-MM-DD" of a Date in the user's LOCAL time zone. (toISOString()
 * would use UTC and shift dates by a day east of Greenwich.) */
export function toLocalIsoDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** This month as the API names months: "2026-03" (local time). */
export function currentMonth(): string {
  return toLocalIsoDate(new Date()).slice(0, 7);
}

export function formatDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  return new Intl.DateTimeFormat(locale, { day: "2-digit", month: "2-digit", year: "numeric" }).format(d);
}

export function formatMonth(month: string): string {
  const [year, m] = month.split("-");
  const d = new Date(Number(year), Number(m) - 1, 1);
  return new Intl.DateTimeFormat(locale, { month: "short", year: "numeric" }).format(d);
}

export function formatBytes(bytes: number): string {
  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${number.format(bytes / 1024)} KB`;
  return `${number.format(bytes / (1024 * 1024))} MB`;
}

/** Date + time in local time. Timestamps without an explicit offset are
 * treated as UTC (that is how the backend stores them). */
export function formatDateTime(iso: string): string {
  if (!iso) return "";
  const hasOffset = /(Z|[+-]\d{2}:?\d{2})$/.test(iso);
  const d = new Date(hasOffset ? iso : `${iso}Z`);
  return new Intl.DateTimeFormat(locale, {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(d);
}

/** strptime format -> human label, e.g. "%d/%m/%Y" -> "DD/MM/YYYY". */
/** "%d.%m.%Y" -> "DD.MM.YYYY" (German: "TT.MM.JJJJ"). */
export function describeDateFormat(fmt: string, t: (key: MessageKey) => string): string {
  return fmt
    .replace("%Y", t("dateFmt.year4"))
    .replace("%y", t("dateFmt.year2"))
    .replace("%m", t("dateFmt.month"))
    .replace("%d", t("dateFmt.day"))
    .replace("%B", t("dateFmt.monthName"))
    .replace("%b", t("dateFmt.monthShort"));
}
