import { useState } from "react";
import { Button, Card, EmptyState, PageHeader } from "../components/ui";
import { BudgetForm } from "../components/budgets/BudgetForm";
import { BudgetProgressRow } from "../components/budgets/BudgetProgressRow";
import { useBudgetStatus } from "../hooks/useBudgets";
import { useI18n } from "../i18n/useI18n";
import { getFormatLocale } from "../lib/format";

function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

// (no <input type="month">: Firefox shows it as a plain text field)
function shiftMonth(month: string, delta: number): string {
  const [year, m] = month.split("-").map(Number);
  const d = new Date(year, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function monthLabel(month: string): string {
  const [year, m] = month.split("-").map(Number);
  return new Intl.DateTimeFormat(getFormatLocale(), { month: "long", year: "numeric" }).format(new Date(year, m - 1, 1));
}

export function Budgets() {
  const { t } = useI18n();
  const [month, setMonth] = useState(currentMonth());
  const [showForm, setShowForm] = useState(false);
  const status = useBudgetStatus(month);

  return (
    <div>
      <PageHeader
        title={t("budgets.title")}
        subtitle={t("budgets.subtitle")}
        actions={
          <Button variant={showForm ? "secondary" : "primary"} onClick={() => setShowForm((v) => !v)}>
            {showForm ? t("common.cancel") : t("budgets.add")}
          </Button>
        }
      />
      <div className="p-8 space-y-6">
        {showForm && (
          <Card className="p-5">
            <BudgetForm onDone={() => setShowForm(false)} />
          </Card>
        )}

        <Card className="p-4 flex items-center gap-2">
          <span className="text-xs text-ink-muted">{t("budgets.month")}</span>
          <button
            type="button"
            aria-label={t("budgets.prevMonth")}
            onClick={() => setMonth(shiftMonth(month, -1))}
            className="px-2 py-1 rounded-md border border-border-strong text-ink-muted hover:bg-surface-sunken"
          >
            ‹
          </button>
          <span aria-live="polite" className="min-w-[9rem] text-center text-sm font-medium text-ink">
            {monthLabel(month)}
          </span>
          <button
            type="button"
            aria-label={t("budgets.nextMonth")}
            onClick={() => setMonth(shiftMonth(month, 1))}
            className="px-2 py-1 rounded-md border border-border-strong text-ink-muted hover:bg-surface-sunken"
          >
            ›
          </button>
          {month !== currentMonth() && (
            <button
              type="button"
              onClick={() => setMonth(currentMonth())}
              className="ml-2 text-xs text-accent-strong underline underline-offset-2"
            >
              {t("budgets.toThisMonth")}
            </button>
          )}
        </Card>

        <Card>
          {status.data && status.data.items.length > 0 ? (
            status.data.items.map((item) => <BudgetProgressRow key={item.category} item={item} />)
          ) : (
            <EmptyState
              title={t("budgets.emptyTitle")}
              description={t("budgets.emptyBody")}
            />
          )}
        </Card>
      </div>
    </div>
  );
}
