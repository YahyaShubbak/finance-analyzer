import { useEffect, useState } from "react";
import { Card, EmptyState, ErrorState } from "../components/ui";
import { TransactionFilterBar } from "../components/transactions/TransactionFilterBar";
import { TransactionTable } from "../components/transactions/TransactionTable";
import { CategoryAssignmentBar } from "../components/transactions/CategoryAssignment";
import { useCategoryAssignment } from "../hooks/useCategoryAssignment";
import { PageHeader } from "../components/ui";
import { useTransactions } from "../hooks/useTransactions";
import { useAccounts } from "../hooks/useAccounts";
import { useFilters } from "../state/filterStore";
import { useCategories, useCategoryNames } from "../hooks/useCategories";
import { useI18n } from "../i18n/useI18n";
import type { TransactionSort } from "../types";

const PAGE_SIZE = 25;
const DEFAULT_SORT: TransactionSort = { key: "date", order: "desc" };

export function Transactions() {
  const { t } = useI18n();
  const [filters, updateFilters, resetFilters] = useFilters();
  const [page, setPage] = useState(1);
  const { data: accounts } = useAccounts();
  const assignment = useCategoryAssignment();
  const categories = useCategoryNames();
  // (the names start as the built-in ones; the user's own arrive with this list)
  const { data: loadedCategories } = useCategories();
  // a saved filter on an account or category that is archived or gone would filter silently
  useEffect(() => {
    const staleAccount = accounts && filters.accountId !== undefined && !accounts.some((a) => a.id === filters.accountId);
    // only once the user's own categories are known: before that, a filter on one of them looks stale
    const staleCategory =
      loadedCategories !== undefined && filters.category !== undefined && !categories.includes(filters.category);
    if (staleAccount || staleCategory) {
      updateFilters({
        ...(staleAccount ? { accountId: undefined } : {}),
        ...(staleCategory ? { category: undefined } : {}),
      });
    }
  }, [accounts, categories, loadedCategories, filters.accountId, filters.category, updateFilters]);

  const [sort, setSort] = useState<TransactionSort>(DEFAULT_SORT);
  const query = useTransactions({
    sort: sort.key,
    order: sort.order,
    account_id: filters.accountId,
    category: filters.category,
    transaction_type: filters.transactionType,
    start: filters.start,
    end: filters.end,
    search: filters.search,
    page,
    page_size: PAGE_SIZE,
  });

  // The last booking of the last page moved away (sorted into another
  // category, removed): show the page before. Set while rendering, so an
  // empty table under "Page 3 of 2" is never shown.
  const total = query.data?.total ?? 0;
  if (query.data && page > 1 && (page - 1) * PAGE_SIZE >= total) {
    setPage(Math.max(1, Math.ceil(total / PAGE_SIZE)));
  }

  function handleFilterChange(patch: Parameters<typeof updateFilters>[0]) {
    updateFilters(patch);
    setPage(1);
  }

  return (
    <div>
      <PageHeader title={t("tx.title")} subtitle={t("tx.subtitle")} />
      <div className="p-8">
        <Card>
          <TransactionFilterBar
            filters={filters}
            onChange={handleFilterChange}
            onReset={() => {
              resetFilters();
              setPage(1);
            }}
            accounts={accounts ?? []}
            categories={categories}
          />
          <CategoryAssignmentBar {...assignment} />
          {query.isError && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
          {query.data && query.data.total === 0 && (
            <EmptyState title={t("transactions.emptyTitle")} description={t("transactions.emptyBody")} />
          )}
          {query.data && query.data.total > 0 && (
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
          )}
        </Card>
      </div>
    </div>
  );
}
