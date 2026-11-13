import type { ReactNode } from "react";
import { Card, EmptyState } from "../ui";
import { IncomeExpenseChart } from "../charts/IncomeExpenseChart";
import { formatMoney } from "../../lib/format";
import type { CategoryBreakdownItem, CurrencyTotals, MonthlyPoint } from "../../types";
import type { MessageKey } from "../../i18n/core";
import { useI18n } from "../../i18n/useI18n";

/**
 * One currency's worth of the overview — stat cards, the income/expense
 * chart and the categories, all scoped to a single currency.
 * Used when the accounts in scope span more than one currency (see
 * Totals.is_mixed_currency): rendered once per currency instead of
 * blending currencies into one meaningless number. `renderCategories`
 * draws the categories (a clickable list).
 */
export function CurrencySection({
  currency,
  totals,
  monthly,
  monthlyFailed,
  categories,
  renderCategories,
}: {
  currency: string;
  totals: CurrencyTotals;
  monthly: MonthlyPoint[];
  /** shown instead of the chart: the months could not be loaded */
  monthlyFailed?: ReactNode;
  categories: CategoryBreakdownItem[];
  renderCategories: (categories: CategoryBreakdownItem[], currency: string) => ReactNode;
}) {
  const { t } = useI18n();
  const monthlyForCurrency = monthly.filter((m) => m.currency === currency);
  const categoriesForCurrency = categories.filter((c) => c.currency === currency);

  return (
    <div className="space-y-6">
      <h3 className="text-xs font-semibold text-ink-muted uppercase tracking-wide">{currency}</h3>
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="stats.income" value={totals.income_minor} currency={currency} tone="income" />
        <StatCard label="stats.expenses" value={totals.expenses_minor} currency={currency} tone="expense" />
        <StatCard label="stats.net" value={totals.net_minor} currency={currency} tone="neutral" />
      </div>

      <Card className="p-5">
        <h2 className="text-sm font-semibold text-ink mb-4">{t("stats.incomeVsExpensesCur", { currency })}</h2>
        {monthlyFailed ?? (monthlyForCurrency.length > 0 ? (
          <IncomeExpenseChart data={monthlyForCurrency} currency={currency} />
        ) : (
          <EmptyState title={t("stats.notEnough")} />
        ))}
      </Card>

      {renderCategories(categoriesForCurrency, currency)}
    </div>
  );
}

function StatCard({
  label,
  value,
  currency,
  tone,
}: {
  label: MessageKey;
  value: number;
  currency: string;
  tone: "income" | "expense" | "neutral";
}) {
  const { t } = useI18n();
  const toneClass = tone === "income" ? "text-income" : tone === "expense" ? "text-expense" : "text-ink";
  return (
    <Card className="p-5">
      <div className="text-xs font-medium text-ink-muted uppercase tracking-wide">{t(label)}</div>
      <div className={`text-2xl font-semibold mt-2 tabular-nums ${toneClass}`}>
        {formatMoney(value, currency)}
      </div>
    </Card>
  );
}
