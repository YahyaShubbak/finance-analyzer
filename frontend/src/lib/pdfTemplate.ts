import type { LayoutWord, PdfTemplate, TemplateColumn } from "../types";

/** What a word of the example booking line is (null: not used). */
export type WordRole = TemplateColumn | null;

// the same patterns as backend/app/importers/pdf_layouts/template.py
const DATE_RE = /^\d{1,2}[./]\d{1,2}[./]?(?:\d{2,4})?$/;
const AMOUNT_RE = /^[-+−]?\(?(?:\d{1,3}(?:[.,' ]\d{3})+|\d+)[.,]\d{2}\)?[-+]?$/;
const SIGN_WORDS = new Set(["-", "−", "+", "S", "H", "DR", "CR", "SOLL", "HABEN"]);

export const EMPTY_TEMPLATE: PdfTemplate = {
  columns: {},
  sign_rule: "as_printed",
  ignore: [],
  labels: {},
  document_type: "bank_statement",
};

/** A first guess at the roles of a booking line's words: the first date is
 * the purchase date (a date right after it the booking date), the last
 * amount is the amount, a sign word right after it its direction, the words
 * between the dates and the amount the text. */
export function suggestRoles(words: LayoutWord[]): WordRole[] {
  const roles: WordRole[] = words.map(() => null);
  let amount = -1;
  for (let i = words.length - 1; i >= 0; i--) {
    if (AMOUNT_RE.test(words[i].text)) {
      amount = i;
      break;
    }
  }
  const end = amount >= 0 ? amount : words.length;
  const dates = words.map((w, i) => (i < end && DATE_RE.test(w.text) ? i : -1)).filter((i) => i >= 0);
  let lastDate = -1;
  if (dates.length > 0) {
    roles[dates[0]] = "date";
    lastDate = dates[0];
    if (dates[1] === dates[0] + 1) {
      roles[dates[1]] = "value_date";
      lastDate = dates[1];
    }
  }
  if (amount >= 0) {
    roles[amount] = "amount";
    const next = words[amount + 1];
    if (next && SIGN_WORDS.has(next.text.toUpperCase())) roles[amount + 1] = "sign";
  }
  for (let i = lastDate + 1; i < end; i++) if (roles[i] === null) roles[i] = "text";
  return roles;
}

/** The template's columns: for each role, from the left edge of its first
 * word to the right edge of its last one. */
export function columnsFrom(words: LayoutWord[], roles: WordRole[]): PdfTemplate["columns"] {
  const columns: PdfTemplate["columns"] = {};
  words.forEach((word, i) => {
    const role = roles[i];
    if (!role) return;
    const range = columns[role];
    columns[role] = range ? [Math.min(range[0], word.x0), Math.max(range[1], word.x1)] : [word.x0, word.x1];
  });
  return columns;
}

/** A line's text without its numbers — how lines to ignore and the lines
 * with totals are recognized in the next statement (as in the backend). */
export function normalizeLine(text: string): string {
  return text.replace(/[\d.,+\-−]+/g, " ").toUpperCase().split(/\s+/).filter(Boolean).join(" ");
}

export function looksLikeDate(text: string): boolean {
  return DATE_RE.test(text);
}

/** Enough to read bookings: where their date and their amount are. */
export function isUsable(template: PdfTemplate): boolean {
  return Boolean(template.columns.date && template.columns.amount);
}
