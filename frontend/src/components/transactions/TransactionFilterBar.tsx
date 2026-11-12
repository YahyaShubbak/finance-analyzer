import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Account } from "../../types";
import type { PersistedFilters } from "../../state/filterStore";
import { categoryLabel } from "../../lib/categories";
import { useI18n } from "../../i18n/useI18n";

/** Search once the typing pauses (as the reports' transaction lists do) —
 * not one request, each scanning every booking, per keystroke. */
export const SEARCH_DELAY_MS = 300;

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

  // What is typed shows at once; the filter follows when the typing pauses.
  const [typed, setTyped] = useState(filters.search ?? "");
  const onChangeRef = useRef(onChange);
  const pending = useRef<string | undefined>(undefined); // typed, not sent yet
  useLayoutEffect(() => {
    onChangeRef.current = onChange;
    pending.current = typed === (filters.search ?? "") ? undefined : typed;
  });
  // the page is left before the pause: what was typed still counts (and is remembered)
  useEffect(
    () => () => {
      if (pending.current !== undefined) onChangeRef.current({ search: pending.current || undefined });
    },
    []
  );
  // the filter changed elsewhere ("Reset", a stale filter cleared): show that
  // (set while rendering, so the old text is never shown)
  const [shownFor, setShownFor] = useState(filters.search);
  if (filters.search !== shownFor) {
    setShownFor(filters.search);
    setTyped(filters.search ?? "");
  }
  useEffect(() => {
    if (typed === (filters.search ?? "")) return;
    const timer = setTimeout(() => onChangeRef.current({ search: typed || undefined }), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [typed, filters.search]);

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
        value={typed}
        onChange={(e) => setTyped(e.target.value)}
      />

      <button onClick={onReset} className="text-xs text-ink-muted hover:text-ink underline underline-offset-2">
        {t("tx.reset")}
      </button>
    </div>
  );
}
