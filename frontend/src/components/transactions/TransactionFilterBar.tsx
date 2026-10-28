import type { Account } from "../../types";
import type { PersistedFilters } from "../../state/filterStore";
import { categoryLabel } from "../../lib/categories";
import { useI18n } from "../../i18n/useI18n";

export function TransactionFilterBar({
  filters,
  onChange,
  onReset,
  accounts,
  categories,
}: {
  filters: PersistedFilters;
  onChange: (patch: Partial<PersistedFilters>) => void;
  onReset: () => void;
  accounts: Account[];
  categories: string[];
}) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap items-center gap-2.5 px-5 py-3.5 border-b border-border bg-surface">
      <select
        className="text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink"
        aria-label={t("col.account")}
        value={filters.accountId ?? ""}
        onChange={(e) => onChange({ accountId: e.target.value ? Number(e.target.value) : undefined })}
      >
        <option value="">{t("tx.allAccounts")}</option>
        {accounts.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name}
          </option>
        ))}
      </select>

      <select
        className="text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink"
        aria-label={t("col.category")}
        value={filters.category ?? ""}
        onChange={(e) => onChange({ category: e.target.value || undefined })}
      >
        <option value="">{t("tx.allCategories")}</option>
        {categories.map((c) => (
          <option key={c} value={c}>
            {categoryLabel(t, c)}
          </option>
        ))}
      </select>

      <select
        className="text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink"
        aria-label={t("col.type")}
        value={filters.transactionType ?? ""}
        onChange={(e) => onChange({ transactionType: (e.target.value || undefined) as PersistedFilters["transactionType"] })}
      >
        <option value="">{t("tx.allTypes")}</option>
        <option value="income">{t("txType.income")}</option>
        <option value="expense">{t("txType.expense")}</option>
        <option value="transfer">{t("txType.transfer")}</option>
      </select>

      <input
        type="date"
        className="text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink"
        aria-label={t("tx.from")}
        value={filters.start ?? ""}
        onChange={(e) => onChange({ start: e.target.value || undefined })}
      />
      <span className="text-ink-faint text-sm">–</span>
      <input
        type="date"
        className="text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink"
        aria-label={t("tx.to")}
        value={filters.end ?? ""}
        onChange={(e) => onChange({ end: e.target.value || undefined })}
      />

      <input
        type="search"
        placeholder={t("tx.search")}
        className="text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink flex-1 min-w-[160px]"
        value={filters.search ?? ""}
        onChange={(e) => onChange({ search: e.target.value || undefined })}
      />

      <button onClick={onReset} className="text-xs text-ink-muted hover:text-ink underline underline-offset-2">
        {t("tx.reset")}
      </button>
    </div>
  );
}
