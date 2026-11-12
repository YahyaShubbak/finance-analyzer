import { useState } from "react";
import { Button, Card, ErrorState } from "../ui";
import { useForgetCategoryRule, useLearnedCategoryRules } from "../../hooks/useRules";
import { categoryLabel } from "../../lib/categories";
import { formatDateTime } from "../../lib/format";
import { useI18n } from "../../i18n/useI18n";

/** What the app learned from category assignments — visible, and undoable. */
export function LearnedRulesSection() {
  const { t, tn } = useI18n();
  const { data: rules, isLoading, isError, error, refetch } = useLearnedCategoryRules();
  const forget = useForgetCategoryRule();
  const [message, setMessage] = useState<string | null>(null);

  return (
    <Card>
      <div className="px-5 py-4 border-b border-border">
        <h2 className="text-sm font-semibold text-ink">{t("learned.title")}</h2>
        <p className="text-xs text-ink-muted mt-1 max-w-lg">{t("learned.body")}</p>
        {message && <p className="text-xs text-income mt-2">{message}</p>}
        {forget.isError && <p className="text-xs text-danger mt-2">{(forget.error as Error).message}</p>}
      </div>
      {/* not an empty list: the rules could not be loaded */}
      {isError && !rules && <ErrorState error={error} onRetry={() => refetch()} />}
      {!isLoading && rules && rules.length === 0 && (
        <div className="px-5 py-6 text-sm text-ink-muted">{t("learned.empty")}</div>
      )}
      {rules && rules.length > 0 && (
        <div className="overflow-x-auto">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-ink-muted text-xs">
                <tr className="border-b border-border">
                  <th className="text-left font-medium px-5 py-2">{t("learned.col.pattern")}</th>
                  <th className="text-left font-medium px-5 py-2">{t("learned.col.category")}</th>
                  <th className="text-right font-medium px-5 py-2">{t("learned.col.matches")}</th>
                  <th className="text-left font-medium px-5 py-2">{t("learned.col.since")}</th>
                  <th className="px-5 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {rules.map((rule) => (
                  <tr key={rule.id} className="border-b border-border last:border-0">
                    <td className="px-5 py-2.5 text-ink">{t("learned.quoted", { pattern: rule.pattern })}</td>
                    <td className="px-5 py-2.5 text-ink-muted">{categoryLabel(t, rule.category)}</td>
                    <td className="px-5 py-2.5 text-right tabular-nums text-ink-muted">{rule.matching_transactions}</td>
                    <td className="px-5 py-2.5 text-ink-muted whitespace-nowrap">{formatDateTime(rule.created_at)}</td>
                    <td className="px-5 py-2.5 text-right">
                      <Button
                        variant="ghost"
                        className="!px-2 !py-1 text-xs"
                        disabled={forget.isPending}
                        onClick={() =>
                          forget.mutate(rule.id, {
                            onSuccess: (result) => setMessage(tn("learned.forgotten", result.transactions_changed)),
                          })
                        }
                      >
                        {t("learned.forget")}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}
