import { Badge } from "../ui";
import { useI18n } from "../../i18n/useI18n";
import { formatDate, formatMoney } from "../../lib/format";
import type { ParsedTransactionPreview, RowClassification, RowDecisionValue } from "../../types";

export function DuplicateRowCard({
  row,
  parsedTx,
  decision,
  onDecisionChange,
}: {
  row: RowClassification;
  parsedTx: ParsedTransactionPreview | undefined;
  decision: RowDecisionValue;
  onDecisionChange: (decision: RowDecisionValue) => void;
}) {
  const { t } = useI18n();
  const isExact = row.status === "exact_duplicate";

  return (
    <div className="rounded-md border border-border p-3">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <div className="text-[11px] font-medium text-ink-faint uppercase tracking-wide mb-1">
                {t("dup.newTx")}
              </div>
              <div className="text-ink">
                {parsedTx?.parsed_date ? formatDate(parsedTx.parsed_date) : parsedTx?.original_date_text}{" "}
                · {row.parsed_merchant ?? parsedTx?.original_description}
              </div>
              <div className="tabular-nums text-ink-muted">
                {parsedTx?.parsed_amount_minor !== null && parsedTx?.parsed_amount_minor !== undefined
                  ? formatMoney(parsedTx.parsed_amount_minor, parsedTx.parsed_currency ?? row.match?.currency ?? "EUR")
                  : parsedTx?.original_amount_text}
              </div>
            </div>
            {row.match && (
              <div>
                <div className="text-[11px] font-medium text-ink-faint uppercase tracking-wide mb-1">
                  {t("dup.existingTx")}
                </div>
                <div className="text-ink">
                  {formatDate(row.match.transaction_date)} · {row.match.merchant ?? row.match.normalized_description}
                </div>
                <div className="tabular-nums text-ink-muted">{formatMoney(row.match.amount_minor, row.match.currency)}</div>
              </div>
            )}
          </div>
          {row.match_reason && <div className="text-xs text-ink-faint mt-2">{t("dup.reason", { reason: row.match_reason })}</div>}
          {row.repeated_in_file && (
            <div className="text-xs text-ink-faint mt-1">{t("dup.repeated")}</div>
          )}
        </div>

        <div className="flex flex-col items-end gap-1.5 shrink-0">
          <Badge tone={isExact ? "neutral" : "warning"}>{isExact ? t("dup.exact") : t("dup.possible")}</Badge>
          <div className="inline-flex rounded-md border border-border-strong overflow-hidden text-xs">
            <button
              type="button"
              onClick={() => onDecisionChange("keep")}
              className={`px-2.5 py-1 ${decision === "keep" ? "bg-accent text-white" : "bg-surface text-ink-muted hover:bg-surface-sunken"}`}
            >
              {t("dup.keep")}
            </button>
            <button
              type="button"
              onClick={() => onDecisionChange("skip")}
              className={`px-2.5 py-1 border-l border-border-strong ${decision === "skip" ? "bg-accent text-white" : "bg-surface text-ink-muted hover:bg-surface-sunken"}`}
            >
              {t("dup.skip")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
