import { Link } from "react-router-dom";
import { Card } from "../ui";
import { currentMonth, formatMoney } from "../../lib/format";
import { useBudgetStatus } from "../../hooks/useBudgets";
import { categoryLabel } from "../../lib/categories";
import { useI18n } from "../../i18n/useI18n";

/** Compact "how am I doing against my budgets" widget — only rendered
 * when budgets exist, so users who haven't set any up yet don't see an
 * empty-state card cluttering the Dashboard. */
export function DashboardBudgetSummary() {
  const { t } = useI18n();
  const status = useBudgetStatus(currentMonth());
  const items = status.data?.items ?? [];
  if (items.length === 0) return null;

  const topItems = [...items].sort((a, b) => b.percent_used - a.percent_used).slice(0, 4);

  return (
    <Card>
      <div className="px-5 py-4 border-b border-border flex items-center justify-between">
        <h2 className="text-sm font-semibold text-ink">{t("budgets.thisMonth")}</h2>
        <Link to="/budgets" className="text-xs text-accent hover:underline">
          {t("budgets.viewAll")}
        </Link>
      </div>
      <div className="p-5 space-y-3">
        {topItems.map((item) => (
          <div key={item.category}>
            <div className="flex items-center justify-between mb-1 text-xs">
              <span className="text-ink">{categoryLabel(t, item.category)}</span>
              <span className={item.over_budget ? "text-danger" : "text-ink-muted"}>
                {formatMoney(item.actual_minor, item.currency)} / {formatMoney(item.budget_minor, item.currency)}
              </span>
            </div>
            <div className="h-1.5 rounded-full bg-surface-sunken overflow-hidden">
              <div
                className={`h-full rounded-full ${item.over_budget ? "bg-danger" : item.percent_used >= 90 ? "bg-warning" : "bg-income"}`}
                style={{ width: `${Math.min(100, item.percent_used)}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
