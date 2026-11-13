import { BreakdownTransactions } from "./BreakdownTransactions";
import { getCategoryTransactions } from "../../api/analytics";
import { categoryLabel } from "../../lib/categories";
import { useI18n } from "../../i18n/useI18n";

/** The transactions behind one category of the overview's breakdown; a
 * transaction moved to another category leaves the list. */
export function CategoryTransactions({
  category,
  currency,
  accountId,
  start,
  end,
  onClose,
}: {
  category: string;
  currency: string;
  /** only this account's transactions; all when not given */
  accountId?: number;
  start?: string;
  end?: string;
  onClose: () => void;
}) {
  const { t } = useI18n();
  return (
    <BreakdownTransactions
      title={t("reports.categoryTransactions", { category: categoryLabel(t, category) })}
      currency={currency}
      queryKey={["category", category, currency, accountId, start, end]}
      fetchPage={(page, page_size, view, signal) =>
        getCategoryTransactions({ ...view, category, currency, account_id: accountId ? String(accountId) : undefined, start, end, page, page_size }, signal)
      }
      emptyText={t("reports.categoryEmpty")}
      onClose={onClose}
    />
  );
}
