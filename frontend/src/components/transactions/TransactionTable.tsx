import { Badge, Pager } from "../ui";
import type { Transaction, TransactionSort, TransactionSortKey } from "../../types";
import { formatDate, formatSignedMoney } from "../../lib/format";
import { categoryLabel } from "../../lib/categories";
import { placeLabel } from "../../lib/places";
import { useI18n } from "../../i18n/useI18n";
import { CategoryCell } from "./CategoryCell";

export function TransactionTable({
  transactions,
  total,
  page,
  pageSize,
  onPageChange,
  onAssignCategory,
  savingId,
  sort,
  onSortChange,
}: {
  transactions: Transaction[];
  total: number;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  /** makes the category column editable */
  onAssignCategory?: (transaction: Transaction, category: string) => void;
  savingId?: number | null;
  /** makes the date, account, type and amount headings sort the list */
  sort?: TransactionSort;
  onSortChange?: (sort: TransactionSort) => void;
}) {
  const { t, tn } = useI18n();
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  function heading(key: TransactionSortKey, label: string, align: "left" | "right" = "left") {
    const className = `${align === "right" ? "text-right" : "text-left"} font-medium px-5 py-2.5`;
    if (!sort || !onSortChange) return <th className={className}>{label}</th>;
    const active = sort.key === key;
    // a new column starts with what is most useful: newest first, amounts
    // from the smallest up (the biggest expense first), A–Z
    const next = active ? (sort.order === "asc" ? "desc" : "asc") : key === "date" ? "desc" : "asc";
    return (
      <th className={className} aria-sort={active ? (sort.order === "asc" ? "ascending" : "descending") : "none"}>
        <button
          type="button"
          onClick={() => onSortChange({ key, order: next })}
          className={`inline-flex items-center gap-1 hover:text-ink ${active ? "text-ink" : ""}`}
          title={t("tx.sortBy", { column: label })}
        >
          {label}
          <span aria-hidden className={active ? "" : "opacity-30"}>
            {active && sort.order === "asc" ? "▲" : "▼"}
          </span>
        </button>
      </th>
    );
  }

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-ink-muted text-xs">
            <tr className="border-b border-border">
              {heading("date", t("col.date"))}
              <th className="text-left font-medium px-5 py-2.5">{t("col.description")}</th>
              <th className="text-left font-medium px-5 py-2.5">{t("col.category")}</th>
              {heading("account", t("col.account"))}
              {heading("type", t("col.type"))}
              {heading("amount", t("col.amount"), "right")}
            </tr>
          </thead>
          <tbody>
            {transactions.map((tx) => (
              <tr key={tx.id} className="border-b border-border last:border-0 hover:bg-surface-sunken/60">
                <td className="px-5 py-2.5 text-ink-muted whitespace-nowrap">{formatDate(tx.transaction_date)}</td>
                <td className="px-5 py-2.5 text-ink">
                  <div className="truncate max-w-[280px]" title={tx.normalized_description}>
                    {tx.merchant ?? tx.normalized_description}
                  </div>
                  {(tx.online || tx.country) && (
                    <div className="text-[11px] text-ink-faint truncate max-w-[280px]">
                      {tx.online ? t("places.online") : placeLabel(tx)}
                    </div>
                  )}
                  {tx.points ? (
                    <span className="text-[11px] text-accent-strong mr-1.5" title={t("points.badgeTitle")}>
                      {t("points.badge", { points: `${tx.points > 0 ? "+" : ""}${tx.points}` })}
                    </span>
                  ) : null}
                  {tx.is_duplicate && (
                    <span className="text-[11px] text-ink-faint">{t("tx.duplicateExcluded")}</span>
                  )}
                  {tx.needs_review && (
                    <span className="text-[11px] text-warning ml-1.5">{t("tx.needsReview")}</span>
                  )}
                </td>
                <td className="px-5 py-2.5 text-ink-muted">
                  {onAssignCategory ? (
                    <CategoryCell transaction={tx} busy={savingId === tx.id} onAssign={onAssignCategory} />
                  ) : (
                    categoryLabel(t, tx.category)
                  )}
                </td>
                <td className="px-5 py-2.5 text-ink-muted">{tx.account_name}</td>
                <td className="px-5 py-2.5">
                  <TypeBadge type={tx.transaction_type} amountMinor={tx.amount_minor} />
                </td>
                <td
                  className={`px-5 py-2.5 text-right tabular-nums font-medium ${
                    tx.is_duplicate || tx.is_transfer ? "text-ink-faint" : tx.amount_minor > 0 ? "text-income" : tx.amount_minor < 0 ? "text-expense" : "text-ink-muted"
                  }`}
                >
                  {formatSignedMoney(tx.amount_minor, tx.currency)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between px-5 py-3 border-t border-border text-xs text-ink-muted">
        <span>
          {tn("tx.count", total)}
        </span>
        <Pager page={page} pages={totalPages} onChange={onPageChange} />
      </div>
    </div>
  );
}

/** A positive expense is money given back for one (a refund): it lowers the
 * spending of its category, so it is shown as such rather than as "Expense". */
function TypeBadge({ type, amountMinor }: { type: Transaction["transaction_type"]; amountMinor: number }) {
  const { t } = useI18n();
  if (type === "expense" && amountMinor > 0) {
    return (
      <span title={t("txType.refundHint")}>
        <Badge tone="income">{t("txType.refund")}</Badge>
      </span>
    );
  }
  if (type === "income") return <Badge tone="income">{t("txType.income")}</Badge>;
  if (type === "expense") return <Badge tone="expense">{t("txType.expense")}</Badge>;
  if (type === "transfer") return <Badge tone="neutral">{t("txType.transfer")}</Badge>;
  return <Badge tone="neutral">{t("txType.unknown")}</Badge>;
}
