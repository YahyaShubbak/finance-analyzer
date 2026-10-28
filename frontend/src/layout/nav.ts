import type { MessageKey } from "../i18n/core";

export interface NavItem {
  labelKey: MessageKey;
  path: string;
  icon: string; // simple inline glyph, no icon library dependency for V1
}

export const NAV_ITEMS: NavItem[] = [
  { labelKey: "nav.dashboard", path: "/", icon: "◧" },
  { labelKey: "nav.transactions", path: "/transactions", icon: "≡" },
  { labelKey: "nav.review", path: "/needs-review", icon: "⚑" },
  { labelKey: "nav.accounts", path: "/accounts", icon: "▤" },
  { labelKey: "nav.creditCards", path: "/credit-cards", icon: "▭" },
  { labelKey: "nav.points", path: "/points", icon: "★" },
  { labelKey: "nav.reconciliation", path: "/reconciliation", icon: "⚖" },
  { labelKey: "nav.imports", path: "/imports", icon: "⇩" },
  { labelKey: "nav.places", path: "/places", icon: "⌖" },
  { labelKey: "nav.budgets", path: "/budgets", icon: "◎" },
  { labelKey: "nav.help", path: "/help", icon: "?" },
  { labelKey: "nav.settings", path: "/settings", icon: "⚙" },
];
