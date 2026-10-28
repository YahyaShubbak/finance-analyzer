import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, EmptyState } from "../ui";
import { TransactionTable } from "../transactions/TransactionTable";
import { CategoryAssignmentBar } from "../transactions/CategoryAssignment";
import { useCategoryAssignment } from "../../hooks/useCategoryAssignment";
import { formatMoney } from "../../lib/format";
import { useI18n } from "../../i18n/useI18n";
import type { ListView } from "../../api/analytics";
import type { CategoryTransactions, TransactionSort } from "../../types";

const PAGE_SIZE = 25;
const DEFAULT_SORT: TransactionSort = { key: "date", order: "desc" };
const SEARCH_DELAY_MS = 300;

interface Props {
  title: string;
  currency: string;
  queryKey: readonly unknown[];
  fetchPage: (page: number, pageSize: number, view: ListView) => Promise<CategoryTransactions>;
  emptyText: string;
  onClose: () => void;
}

/** The transactions behind one row of a breakdown (a category, a place), in
 * the same period — they add up to the row's amount. They can be searched
 * and sorted, and categories corrected right here. `queryKey` identifies
 * the row: a new one starts afresh (page 1, no search) and is scrolled into view. */
export function BreakdownTransactions(props: Props) {
  return <RowTransactions key={JSON.stringify(props.queryKey)} {...props} />;
}

function RowTransactions({ title, currency, queryKey, fetchPage, emptyText, onClose }: Props) {
  const { t, tn } = useI18n();
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<TransactionSort>(DEFAULT_SORT);
  const [typed, setTyped] = useState("");
  const [search, setSearch] = useState("");
  const assignment = useCategoryAssignment();
  const view: ListView = { search: search || undefined, sort: sort.key, order: sort.order };
  const query = useQuery({
    queryKey: ["breakdown-transactions", ...queryKey, view, page],
    queryFn: () => fetchPage(page, PAGE_SIZE, view),
    placeholderData: (prev) => prev, // keep the list while paging, sorting or searching
  });
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    heading.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, []);

  // search once the typing pauses
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(typed.trim());
      setPage(1);
    }, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [typed]);

  // the last transaction of the last page moved away: show the page before
  // (set while rendering, so the empty page is never shown)
  const total = query.data?.total ?? 0;
  if (query.data && page > 1 && (page - 1) * PAGE_SIZE >= total) {
    setPage(Math.max(1, Math.ceil(total / PAGE_SIZE)));
  }

  return (
    <Card>
      <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-border">
        <div>
          <h2 ref={heading} tabIndex={-1} className="text-sm font-semibold text-ink scroll-mt-4">
            {title}
          </h2>
          {query.data && (
            <p className="text-xs text-ink-muted mt-0.5">
              {tn("reports.categoryTotal", query.data.total, { amount: formatMoney(query.data.amount_minor, currency) })}
            </p>
          )}
        </div>
        <div className="flex items-center gap-4">
          <input
            type="search"
            placeholder={t("tx.search")}
            aria-label={t("tx.search")}
            className="text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink w-56"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
          />
          <button
            type="button"
            onClick={onClose}
            className="text-xs text-ink-muted underline underline-offset-2 hover:text-ink"
          >
            {t("common.close")}
          </button>
        </div>
      </div>
      <CategoryAssignmentBar {...assignment} />
      {query.isError ? (
        <div className="px-5 py-4 text-sm text-danger">{(query.error as Error).message}</div>
      ) : query.data && query.data.total === 0 ? (
        <div className="px-5 py-6">
          <EmptyState title={search ? t("transactions.emptyTitle") : emptyText} />
        </div>
      ) : query.data ? (
        <TransactionTable
          transactions={query.data.items}
          total={query.data.total}
          page={page}
          pageSize={PAGE_SIZE}
          onPageChange={setPage}
          onAssignCategory={assignment.assign}
          savingId={assignment.savingId}
          sort={sort}
          onSortChange={(next) => {
            setSort(next);
            setPage(1);
          }}
        />
      ) : (
        <div className="px-5 py-4 text-sm text-ink-muted">{t("common.loading")}</div>
      )}
    </Card>
  );
}
