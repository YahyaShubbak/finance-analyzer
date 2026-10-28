import { formatMoney } from "./format";
import type { MessageKey } from "../i18n/core";
import type { AccountType } from "../types";

export interface AccountBalanceDisplay {
  labelKey: MessageKey;
  value: string;
  tone: "income" | "expense" | "neutral";
}

/**
 * For credit cards, a raw signed balance is ambiguous to a non-technical
 * reader ("-€120.00" — owed? overpaid? refunded?). This makes the
 * accounting convention explicit in the label itself, without changing
 * the underlying number (balance_minor is still a plain net-of-imported-
 * transactions figure, computed the same way for every account type).
 */
export function formatAccountBalance(
  balanceMinor: number,
  accountType: AccountType,
  currency: string
): AccountBalanceDisplay {
  if (accountType === "credit_card") {
    if (balanceMinor < 0) {
      return { labelKey: "balance.owed", value: formatMoney(-balanceMinor, currency), tone: "expense" };
    }
    if (balanceMinor > 0) {
      return { labelKey: "balance.credit", value: formatMoney(balanceMinor, currency), tone: "income" };
    }
    return { labelKey: "balance.owed", value: formatMoney(0, currency), tone: "neutral" };
  }

  return {
    labelKey: "balance.balance",
    value: formatMoney(balanceMinor, currency),
    tone: balanceMinor >= 0 ? "income" : "expense",
  };
}
