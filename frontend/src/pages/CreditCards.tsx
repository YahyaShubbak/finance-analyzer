import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Card, EmptyState, ErrorState, PageHeader, ReconciliationStatusBadge } from "../components/ui";
import { useCreditCards, useStatements } from "../hooks/useCreditCards";
import { formatDate, formatMoney } from "../lib/format";
import { formatAccountBalance } from "../lib/accountBalance";
import type { CreditCardSummary } from "../types";
import { useI18n } from "../i18n/useI18n";

export function CreditCards() {
  const { t } = useI18n();
  const { data: cards, isLoading, isError, error, refetch } = useCreditCards();

  return (
    <div>
      <PageHeader title={t("cards.title")} subtitle={t("cards.subtitle")} />
      <div className="p-8 space-y-5">
        {/* not "no credit cards": they could not be loaded (the app stopped, an error) */}
        {isError && !cards && (
          <Card>
            <ErrorState error={error} onRetry={() => refetch()} />
          </Card>
        )}
        {!isLoading && !isError && (!cards || cards.length === 0) && (
          <Card>
            <EmptyState
              title={t("cards.emptyTitle")}
              description={t("cards.emptyBody")}
            />
          </Card>
        )}
        {cards?.map((c) => (
          <CreditCardPanel key={c.account.id} summary={c} />
        ))}
      </div>
    </div>
  );
}

function CreditCardPanel({ summary }: { summary: CreditCardSummary }) {
  const { t, tn } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const statements = useStatements(expanded ? summary.account.id : undefined);
  const navigate = useNavigate();
  const { account, latest_statement } = summary;
  // A card whose files are booking lists (an export), not statements: its
  // payments are paired one by one with the bank debits instead.
  const payments = summary.payments_linked + summary.payments_unlinked;
  const statementless = summary.statement_count === 0 && payments > 0;

  return (
    <Card>
      <button
        type="button"
        aria-expanded={expanded}
        className="w-full text-left flex items-center justify-between px-5 py-4 cursor-pointer rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        onClick={() => setExpanded((v) => !v)}
      >
        <div>
          <div className="text-sm font-semibold text-ink">{account.name}</div>
          <div className="text-xs text-ink-muted mt-0.5">
            {statementless
              ? t("cards.linkedPayments", { linked: summary.payments_linked, total: payments })
              : tn("cards.statements", summary.statement_count)}{" "}
            · {tn("cards.transactions", account.transaction_count)} ·{" "}
            {(() => {
              const b = formatAccountBalance(account.current_balance_minor, account.account_type, account.currency);
              return `${t(b.labelKey)}: ${b.value}`;
            })()}
          </div>
        </div>
        <div className="flex items-center gap-3">
          {latest_statement && (
            <>
              <div className="text-right">
                <div className="text-xs text-ink-faint">{t("cards.latest")}</div>
                <div className="text-sm font-medium tabular-nums text-ink">
                  {latest_statement.statement_total_minor !== null
                    ? formatMoney(latest_statement.statement_total_minor, latest_statement.currency)
                    : "—"}
                </div>
              </div>
              <ReconciliationStatusBadge status={latest_statement.reconciliation_status} />
            </>
          )}
          <span aria-hidden className="text-ink-faint text-xs">{expanded ? "▲" : "▼"}</span>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-border">
          {statements.data && statements.data.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-ink-muted text-xs">
                  <tr className="border-b border-border">
                    <th className="text-left font-medium px-5 py-2">{t("cards.period")}</th>
                    <th className="text-right font-medium px-5 py-2">{t("cards.total")}</th>
                    <th className="text-right font-medium px-5 py-2">{t("cards.txCount")}</th>
                    <th className="text-right font-medium px-5 py-2">{t("recon.difference")}</th>
                    <th className="text-right font-medium px-5 py-2">{t("col.status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {statements.data.map((s) => (
                    <tr
                      key={s.id}
                      className="border-b border-border last:border-0 hover:bg-surface-sunken/60 cursor-pointer"
                      onClick={() => navigate(`/reconciliation/${s.id}`)}
                    >
                      <td className="px-5 py-2.5 text-ink">
                        <Link
                          to={`/reconciliation/${s.id}`}
                          onClick={(e) => e.stopPropagation()}
                          className="hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent rounded-sm"
                        >
                          {s.statement_period_start && s.statement_period_end
                            ? `${formatDate(s.statement_period_start)} – ${formatDate(s.statement_period_end)}`
                            : t("recon.unknownPeriod")}
                        </Link>
                      </td>
                      <td className="px-5 py-2.5 text-right tabular-nums text-ink">
                        {s.statement_total_minor !== null ? formatMoney(s.statement_total_minor, s.currency) : "—"}
                      </td>
                      <td className="px-5 py-2.5 text-right tabular-nums text-ink-muted">{s.transaction_count}</td>
                      <td className="px-5 py-2.5 text-right tabular-nums text-ink-muted">
                        {s.difference_minor !== null && s.difference_minor !== 0
                          ? formatMoney(s.difference_minor, s.currency)
                          : "—"}
                      </td>
                      <td className="px-5 py-2.5 text-right">
                        <ReconciliationStatusBadge status={s.reconciliation_status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            statementless ? (
              <div className="px-5 py-4 space-y-2 text-sm text-ink-muted max-w-3xl">
                <p>{t("cards.statementlessBody")}</p>
                <p>
                  {tn("cards.paymentsLinked", summary.payments_linked)}
                  {summary.payments_unlinked > 0 && <> {tn("cards.paymentsUnlinked", summary.payments_unlinked)}</>}
                </p>
                <p className="text-xs">{t("cards.reconciliationHint")}</p>
              </div>
            ) : (
              <div className="px-5 py-6">
                <EmptyState title={t("cards.noStatements")} />
              </div>
            )
          )}
        </div>
      )}
    </Card>
  );
}
