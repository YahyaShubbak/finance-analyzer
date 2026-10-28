import { Badge } from "../ui";
import { useI18n } from "../../i18n/useI18n";

export function ImportSummaryCounts({
  newCount,
  exactCount,
  possibleCount,
  needsReviewCount,
}: {
  newCount: number;
  exactCount: number;
  possibleCount: number;
  needsReviewCount: number;
}) {
  const { t, tn } = useI18n();
  return (
    <div className="flex flex-wrap gap-2">
      <Badge tone="income">{t("imports.new", { count: newCount })}</Badge>
      {exactCount > 0 && <Badge tone="neutral">{tn("imports.exact", exactCount)}</Badge>}
      {possibleCount > 0 && (
        <Badge tone="warning">{tn("imports.possible", possibleCount)}</Badge>
      )}
      {needsReviewCount > 0 && (
        <Badge tone="warning">{tn("imports.review", needsReviewCount)}</Badge>
      )}
    </div>
  );
}
