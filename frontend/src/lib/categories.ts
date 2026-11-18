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

/** Categories of money received: a booking in one of them is income. */
const INCOME_CATEGORIES = new Set(["Salary", "Other Income"]);
/** Money between the user's own accounts: neither spending nor income. */
const NOT_SPENDING = new Set(["Transfers", "Card bills"]);

/** What choosing `category` for `tx` means for how it is counted:
 * - "ask": money that came in gets a category of spending — a refund (it
 *   lowers that category's spending, e.g. reimbursed travel costs) or
 *   income? Only the user knows.
 * - "income": a refund gets a category of income: it is income again.
 * - null: nothing changes. */
export function countingOf(
  tx: { amount_minor: number; transaction_type: string; is_transfer: boolean },
  category: string
): "ask" | "income" | null {
  if (tx.amount_minor <= 0 || tx.is_transfer || NOT_SPENDING.has(category)) return null;
  const refund = tx.transaction_type === "expense";
  if (INCOME_CATEGORIES.has(category)) return refund ? "income" : null;
  return refund ? null : "ask";
}

/** Display name of a category: translated for built-in ones, user-defined ones as typed. */
export function categoryLabel(t: (key: MessageKey) => string, category: string | null | undefined): string {
  if (!category) return "—";
  return BUILT_IN.has(category) ? t(`category.${category}` as MessageKey) : category;
}
