import { useId, useState } from "react";
import { Button } from "../ui";
import { useBudgets, useUpsertBudget } from "../../hooks/useBudgets";
import { CATEGORIES, categoryLabel } from "../../lib/categories";
import { useCategoryNames } from "../../hooks/useCategories";
import { useI18n } from "../../i18n/useI18n";

const CURRENCIES = ["EUR", "USD", "GBP", "CHF"];

export function BudgetForm({
  onDone,
  initial,
}: {
  onDone: () => void;
  /** edit this budget (its category stays) instead of adding one */
  initial?: { category: string; amount_minor: number; currency: string };
}) {
  const { t } = useI18n();
  const ids = useId();
  const categories = useCategoryNames();
  const { data: budgets } = useBudgets();
  const [category, setCategory] = useState(initial?.category ?? CATEGORIES[0]);
  const [amount, setAmount] = useState(initial ? (initial.amount_minor / 100).toFixed(2) : "");
  const [currency, setCurrency] = useState(initial?.currency ?? "EUR");
  const upsert = useUpsertBudget();
  const replaces = !initial && budgets?.some((b) => b.category === category);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const parsed = Number(amount);
    if (Number.isNaN(parsed) || parsed <= 0) return;
    upsert.mutate(
      { category, amountMinor: Math.round(parsed * 100), currency },
      {
        onSuccess: () => {
          setAmount("");
          onDone();
        },
      }
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor={`${ids}-category`} className="text-xs text-ink-muted">{t("budgets.category")}</label>
        <select
          id={`${ids}-category`}
          disabled={Boolean(initial)}
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="text-sm border border-border-strong rounded-md px-2.5 py-2 bg-surface text-ink w-44"
        >
          {categories.map((c) => (
            <option key={c} value={c}>
              {categoryLabel(t, c)}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor={`${ids}-amount`} className="text-xs text-ink-muted">{t("budgets.amount")}</label>
        <input
          id={`${ids}-amount`}
          type="number"
          step="0.01"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder={t("budgets.amountPlaceholder")}
          className="text-sm border border-border-strong rounded-md px-2.5 py-2 bg-surface text-ink w-32"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor={`${ids}-currency`} className="text-xs text-ink-muted">{t("budgets.currency")}</label>
        <select
          id={`${ids}-currency`}
          value={currency}
          onChange={(e) => setCurrency(e.target.value)}
          className="text-sm border border-border-strong rounded-md px-2.5 py-2 bg-surface text-ink"
        >
          {CURRENCIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>
      <Button type="submit" variant="primary" disabled={!amount || Number(amount) <= 0 || upsert.isPending}>
        {upsert.isPending ? t("common.saving") : t("budgets.save")}
      </Button>
      {replaces && <div className="text-xs text-warning w-full">{t("budgets.replaces")}</div>}
      {upsert.isError && <div className="text-xs text-danger w-full">{(upsert.error as Error).message}</div>}
    </form>
  );
}
