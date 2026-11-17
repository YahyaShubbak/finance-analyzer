import { useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "../../i18n/useI18n";
import type { MessageKey } from "../../i18n/core";
import { Button, Card, EmptyState, ErrorState } from "../ui";
import { ImportHistoryRow } from "./ImportHistoryRow";
import { useImportHistory, useRemoveImports } from "../../hooks/useImports";
import type { ImportRecord } from "../../types";
import { billingMonths, formatMonthLong } from "../../lib/billingPeriod";

type SortKey = "filename" | "account_name" | "document_type" | "period_end" | "imported_at" | "detected_transaction_count";

const COLUMNS: { key: SortKey; label: MessageKey; align?: "right" }[] = [
  { key: "filename", label: "imports.col.file" },
  { key: "account_name", label: "imports.col.account" },
  { key: "document_type", label: "imports.col.type" },
  { key: "period_end", label: "imports.col.period" },
  { key: "imported_at", label: "imports.col.imported" },
  { key: "detected_transaction_count", label: "imports.col.rows", align: "right" },
];

function compare(a: ImportRecord, b: ImportRecord, key: SortKey): number {
  const x = a[key], y = b[key];
  if (typeof x === "number" && typeof y === "number") return x - y;
  return String(x ?? "").localeCompare(String(y ?? ""), undefined, { numeric: true, sensitivity: "base" });
}

/** The import history: filter by account, sort by any column, select
 * several (or all shown) imports and remove them in one go. */
export function ImportHistory() {
  const { t, tn } = useI18n();
  const history = useImportHistory();
  const removeMany = useRemoveImports();
  const [accountId, setAccountId] = useState<number | "all">("all");
  // "all", a year ("2026") or a month ("2026-07")
  const [period, setPeriod] = useState("all");
  const [sort, setSort] = useState<{ key: SortKey; descending: boolean }>({ key: "imported_at", descending: true });
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);
  const selectAll = useRef<HTMLInputElement>(null);

  const records = useMemo(() => history.data ?? [], [history.data]);
  const accounts = useMemo(() => {
    const byId = new Map<number, string>();
    records.forEach((r) => byId.set(r.account_id, r.account_name));
    return [...byId.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [records]);
  // a filter on an account whose imports are all gone falls back to "all"
  const filter = accountId !== "all" && records.some((r) => r.account_id === accountId) ? accountId : "all";
  const ofAccount = useMemo(
    () => records.filter((r) => filter === "all" || r.account_id === filter),
    [records, filter],
  );
  // the years and months the account's imports are about, newest first
  const periods = useMemo(() => {
    const byYear = new Map<string, Set<string>>();
    for (const r of ofAccount) {
      for (const m of billingMonths(r.period_start, r.period_end)) {
        if (!byYear.has(m.slice(0, 4))) byYear.set(m.slice(0, 4), new Set());
        byYear.get(m.slice(0, 4))!.add(m);
      }
    }
    return [...byYear.entries()].sort((a, b) => b[0].localeCompare(a[0]))
      .map(([year, months]) => [year, [...months].sort().reverse()] as const);
  }, [ofAccount]);
  // a period no import of the account is about any more falls back to "all"
  const periodFilter = periods.some(([year, months]) => year === period || months.includes(period)) ? period : "all";
  const shown = useMemo(() => {
    const rows = ofAccount.filter((r) => periodFilter === "all"
      || billingMonths(r.period_start, r.period_end).some((m) => m.startsWith(periodFilter)));
    rows.sort((a, b) => compare(a, b, sort.key) * (sort.descending ? -1 : 1) || b.id - a.id);
    return rows;
  }, [ofAccount, periodFilter, sort]);

  // only what is shown can be selected
  const visibleSelected = shown.filter((r) => selected.has(r.id));
  const allShownSelected = shown.length > 0 && visibleSelected.length === shown.length;
  useEffect(() => {
    if (selectAll.current) selectAll.current.indeterminate = visibleSelected.length > 0 && !allShownSelected;
  }, [visibleSelected.length, allShownSelected]);

  function toggle(id: number) {
    setSummary(null);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSummary(null);
    setSelected(allShownSelected ? new Set() : new Set(shown.map((r) => r.id)));
  }

  function changeAccount(value: string) {
    setAccountId(value === "all" ? "all" : Number(value));
    setSelected(new Set());
    setConfirming(false);
  }

  function changePeriod(value: string) {
    setPeriod(value);
    setSelected(new Set());
    setConfirming(false);
  }

  function sortBy(key: SortKey) {
    setSort((prev) => ({ key, descending: prev.key === key ? !prev.descending : key === "imported_at" }));
  }

  function removeSelected() {
    const ids = visibleSelected.map((r) => r.id);
    removeMany.mutate(ids, {
      onSuccess: (result) => {
        setSelected(new Set());
        setConfirming(false);
        setSummary(tn("imports.removedSummary", result.transactions_removed, { imports: tn("imports.importsCount", result.imports_removed) }));
      },
    });
  }

  const rowsSelected = visibleSelected.reduce((sum, r) => sum + r.detected_transaction_count, 0);

  return (
    <Card>
      <div className="px-5 py-4 border-b border-border flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-ink">{t("imports.history")}</h2>
        <div className="flex flex-wrap items-center gap-2">
        {periods.length > 0 && (
          <select
            aria-label={t("imports.filterPeriod")}
            className="text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink"
            value={periodFilter}
            onChange={(e) => changePeriod(e.target.value)}
          >
            <option value="all">{t("imports.allPeriods")}</option>
            {periods.map(([year, months]) => (
              <optgroup key={year} label={year}>
                <option value={year}>{t("imports.wholeYear", { year })}</option>
                {months.map((m) => (
                  <option key={m} value={m}>
                    {formatMonthLong(m)}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        )}
        {accounts.length > 1 && (
          <select
            aria-label={t("imports.filterAccount")}
            className="text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink"
            value={filter}
            onChange={(e) => changeAccount(e.target.value)}
          >
            <option value="all">{t("tx.allAccounts")}</option>
            {accounts.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        )}
        </div>
      </div>

      {(visibleSelected.length > 0 || summary) && (
        <div className="px-5 py-3 border-b border-border bg-surface-sunken/60 space-y-2" role="status" aria-live="polite">
          {summary && <p className="text-xs text-income">{summary}</p>}
          {visibleSelected.length > 0 && !confirming && (
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm text-ink">{tn("imports.selected", visibleSelected.length)}</span>
              <Button variant="secondary" className="!px-2.5 !py-1 text-xs" onClick={() => setConfirming(true)}>
                {t("imports.removeSelected")}
              </Button>
            </div>
          )}
          {confirming && visibleSelected.length > 0 && (
            <div className="rounded-md bg-danger-soft border border-danger/30 p-3 space-y-3">
              <p className="text-sm text-ink">
                {tn("imports.removeSelectedConfirm", visibleSelected.length, { rows: rowsSelected })}
              </p>
              {removeMany.isError && <p className="text-xs text-danger">{(removeMany.error as Error).message}</p>}
              <div className="flex gap-2">
                <Button variant="primary" className="!bg-danger hover:!bg-danger" disabled={removeMany.isPending}
                        onClick={removeSelected}>
                  {removeMany.isPending ? t("imports.removing") : tn("imports.removeSelectedYes", visibleSelected.length)}
                </Button>
                <Button variant="ghost" onClick={() => setConfirming(false)} disabled={removeMany.isPending}>
                  {t("common.cancel")}
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {shown.length > 0 ? (
        <div className="overflow-x-auto">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-ink-muted text-xs">
                <tr className="border-b border-border">
                  {COLUMNS.map((column) => {
                    const active = sort.key === column.key;
                    return (
                      <th
                        key={column.key}
                        aria-sort={active ? (sort.descending ? "descending" : "ascending") : "none"}
                        className={`font-medium px-3 first:pl-5 py-2.5 ${column.align === "right" ? "text-right" : "text-left"}`}
                        title={column.key === "detected_transaction_count" ? t("imports.col.rowsHint") : undefined}
                      >
                        <button
                          type="button"
                          onClick={() => sortBy(column.key)}
                          aria-label={t("imports.sortBy", { column: t(column.label) })}
                          className={`inline-flex items-center gap-1 hover:text-ink ${active ? "text-ink" : ""}`}
                        >
                          {t(column.label)}
                          <span aria-hidden className={active ? "" : "opacity-0"}>{sort.descending ? "▼" : "▲"}</span>
                        </button>
                      </th>
                    );
                  })}
                  <th className="pl-3 pr-5 py-2.5 text-right font-medium">
                    <label className="inline-flex items-center gap-1.5 cursor-pointer whitespace-nowrap">
                      <input ref={selectAll} type="checkbox" checked={allShownSelected} onChange={toggleAll} />
                      {t("imports.selectAll")}
                    </label>
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <ImportHistoryRow key={r.id} record={r} selected={selected.has(r.id)} onToggle={() => toggle(r.id)} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : history.isError && !history.data ? (
        // not "no imports yet": they could not be loaded
        <ErrorState error={history.error} onRetry={() => history.refetch()} />
      ) : (
        <EmptyState title={t("imports.emptyTitle")} description={t("imports.emptyBody")} />
      )}
    </Card>
  );
}
