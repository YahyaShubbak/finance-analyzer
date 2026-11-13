import { useState } from "react";
import { Button } from "../ui";
import { BudgetForm } from "./BudgetForm";
import { formatMoney } from "../../lib/format";
import { useBudgets, useDeleteBudget } from "../../hooks/useBudgets";
import { categoryLabel } from "../../lib/categories";
import type { BudgetStatusItem } from "../../types";
import { useI18n } from "../../i18n/useI18n";

export function BudgetProgressRow({ item }: { item: BudgetStatusItem }) {
  const { t } = useI18n();
  const { data: budgets } = useBudgets();
  const del = useDeleteBudget();
  const budget = budgets?.find((b) => b.category === item.category);
  const budgetId = budget?.id;
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const barWidth = Math.min(100, item.percent_used);
  const barClass = item.over_budget ? "bg-danger" : item.percent_used >= 90 ? "bg-warning" : "bg-income";

  return (
    <div className="px-5 py-3 border-b border-border last:border-0">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-sm text-ink font-medium">{categoryLabel(t, item.category)}</span>
        <div className="flex items-center gap-2">
          <span className={`text-sm tabular-nums ${item.over_budget ? "text-danger" : "text-ink-muted"}`}>
            {formatMoney(item.actual_minor, item.currency)} / {formatMoney(item.budget_minor, item.currency)}
          </span>
          {budget && (
            <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => setEditing((v) => !v)}>
              {editing ? t("common.cancel") : t("common.edit")}
            </Button>
          )}
          {budgetId !== undefined && !confirming && (
            <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => setConfirming(true)}>
              {t("common.remove")}
            </Button>
          )}
        </div>
      </div>
      {confirming && budgetId !== undefined && (
        <div className="my-2 rounded-md bg-danger-soft/40 px-3 py-2">
          <p className="text-sm text-ink">{t("budgets.removeConfirm", { category: categoryLabel(t, item.category) })}</p>
          {del.isError && <p className="text-xs text-danger mt-1">{(del.error as Error).message}</p>}
          <div className="mt-2 flex gap-2">
            <Button
              variant="primary"
              className="!bg-danger hover:!bg-danger !py-1 text-xs"
              disabled={del.isPending}
              onClick={() => del.mutate(budgetId, { onSuccess: () => setConfirming(false) })}
            >
              {t("budgets.removeYes")}
            </Button>
            <Button
              variant="ghost"
              className="!py-1 text-xs"
              disabled={del.isPending}
              onClick={() => {
                del.reset();
                setConfirming(false);
              }}
            >
              {t("common.cancel")}
            </Button>
          </div>
        </div>
      )}
      {editing && budget && (
        <div className="my-3">
          <BudgetForm initial={budget} onDone={() => setEditing(false)} />
        </div>
      )}
      <div className="h-2 rounded-full bg-surface-sunken overflow-hidden">
        <div className={`h-full rounded-full ${barClass}`} style={{ width: `${barWidth}%` }} />
      </div>
    </div>
  );
}
