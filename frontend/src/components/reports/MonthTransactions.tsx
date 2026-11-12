import { useEffect, useRef, useState } from "react";
import { Card, EmptyState } from "../ui";
import { TransactionTable } from "../transactions/TransactionTable";
import { CategoryAssignmentBar } from "../transactions/CategoryAssignment";
import { useCategoryAssignment } from "../../hooks/useCategoryAssignment";
import { useTransactions } from "../../hooks/useTransactions";
import { formatMoney, formatMonth } from "../../lib/format";
import { useI18n } from "../../i18n/useI18n";
import type { MonthlyPoint, TransactionSort } from "../../types";

const PAGE_SIZE = 25;

/** The month, within the report's period (ISO dates compare as strings). */
function monthRange(month: string, rangeStart?: string, rangeEnd?: string): { start: string; end: string } {
  const [year, m] = month.split("-").map(Number);
  const last = new Date(year, m, 0).getDate(); // day 0 of the next month
  const start = `${month}-01`;
  const end = `${month}-${String(last).padStart(2, "0")}`;
  return {
    start: rangeStart && rangeStart > start ? rangeStart : start,
    end: rangeEnd && rangeEnd < end ? rangeEnd : end,
  };
}

/** Every booking of one month (on the chosen account or all) — what the month's bars are
 * made of, plus the transfers between own accounts (shown, not counted). */
export function MonthTransactions({
  point,
  currency,
  accountId,
  rangeStart,
  rangeEnd,
  onClose,
}: {
  point: MonthlyPoint;
  currency: string;
  /** only this account's bookings; all when not given */
  accountId?: number;
  /** the report's period: the list shows what the month's bars count */
  rangeStart?: string;
  rangeEnd?: string;
  onClose: () => void;
}) {
  const { t, tn } = useI18n();
  const [paging, setPaging] = useState({ month: point.month, page: 1 });
  const page = paging.month === point.month ? paging.page : 1;
  const [sort, setSort] = useState<TransactionSort>({ key: "date", order: "asc" });
  const assignment = useCategoryAssignment();
  const { start, end } = monthRange(point.month, rangeStart, rangeEnd);
  const query = useTransactions({
    start,
    end,
    account_id: accountId,
    include_transfers: true,
    active_accounts_only: true,
    sort: sort.key,
    order: sort.order,
    page,
    page_size: PAGE_SIZE,
  });
  // The last booking of the last page moved away: show the page before
  // (set while rendering, so an empty table under "Page 3 of 2" is never shown).
  const total = query.data?.total ?? 0;
  if (query.data && page > 1 && (page - 1) * PAGE_SIZE >= total) {
    setPaging({ month: point.month, page: Math.max(1, Math.ceil(total / PAGE_SIZE)) });
  }
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    heading.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [point.month]);

  return (
    <Card>
      <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-border">
        <div>
          <h2 ref={heading} tabIndex={-1} className="text-sm font-semibold text-ink scroll-mt-4">
            {t("reports.monthTitle", { month: formatMonth(point.month) })}
          </h2>
          <p className="text-xs text-ink-muted mt-0.5">
            {query.data && `${tn("tx.count", query.data.total)} · `}
            <span className="text-income">{t("stats.income")} {formatMoney(point.income_minor, currency)}</span>
            {" · "}
            <span className="text-expense">{t("stats.expenses")} {formatMoney(point.expenses_minor, currency)}</span>
          </p>
          <p className="text-xs text-ink-faint mt-0.5">{t("reports.monthHint")}</p>
        </div>
        <button type="button" onClick={onClose} className="text-xs text-ink-muted underline underline-offset-2 hover:text-ink">
          {t("common.close")}
        </button>
      </div>
      <CategoryAssignmentBar {...assignment} />
      {query.isError ? (
        <div className="px-5 py-4 text-sm text-danger">{(query.error as Error).message}</div>
      ) : query.data && query.data.total === 0 ? (
        <div className="px-5 py-6">
          <EmptyState title={t("dash.noTxPeriod")} />
        </div>
      ) : query.data ? (
        <TransactionTable
          transactions={query.data.items}
          total={query.data.total}
          page={page}
          pageSize={PAGE_SIZE}
          onPageChange={(next) => setPaging({ month: point.month, page: next })}
          onAssignCategory={assignment.assign}
          savingId={assignment.savingId}
          sort={sort}
          onSortChange={(next) => {
            setSort(next);
            setPaging({ month: point.month, page: 1 });
          }}
        />
      ) : (
        <div className="px-5 py-4 text-sm text-ink-muted">{t("common.loading")}</div>
      )}
    </Card>
  );
}
