import type { MessageKey } from "../i18n/core";

// Built-in categories, mirroring backend/app/normalization/category.py.
// Stored in the database under these (English) names; shown translated.
export const CATEGORIES = [
  "Food",
  "Groceries",
  "Housing",
  "Transport",
  "Travel",
  "Shopping",
  "Subscriptions",
  "Entertainment",
  "Health",
  "Education",
  "Utilities",
  "Insurance",
  "Taxes",
  "Cash",
  "Fees",
  "Donations",
  "Salary",
  "Other Income",
  "Other Expense",
  "Transfers",
  "Card bills",
];

const BUILT_IN = new Set(CATEGORIES);

/** Display name of a category: translated for built-in ones, user-defined ones as typed. */
export function categoryLabel(t: (key: MessageKey) => string, category: string | null | undefined): string {
  if (!category) return "—";
  return BUILT_IN.has(category) ? t(`category.${category}` as MessageKey) : category;
}
