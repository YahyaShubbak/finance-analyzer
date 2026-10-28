import { BreakdownBars } from "./BreakdownBars";
import { categoryLabel } from "../../lib/categories";
import { useI18n } from "../../i18n/useI18n";
import type { CategoryBreakdownItem } from "../../types";

/** Spending per category (one currency). Choosing a category shows its
 * transactions (see CategoryTransactions), choosing it again hides them. */
export function CategoryBreakdownList({
  data,
  currency,
  selected,
  onSelect,
}: {
  data: CategoryBreakdownItem[];
  currency: string;
  selected: string | null;
  onSelect: (category: string | null) => void;
}) {
  const { t } = useI18n();
  return (
    <div>
      <p className="text-xs text-ink-muted mb-3">{t("reports.categoryHint")}</p>
      <BreakdownBars
        items={data.map((d) => ({ key: d.category, label: categoryLabel(t, d.category), amount_minor: d.amount_minor }))}
        currency={currency}
        selected={selected}
        onSelect={onSelect}
      />
    </div>
  );
}
