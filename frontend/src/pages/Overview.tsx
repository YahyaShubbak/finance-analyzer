import { useEffect, useState } from "react";
import { Badge, Card, EmptyState, ErrorState, PageHeader } from "../components/ui";
import { DateRangeSelector } from "../components/reports/DateRangeSelector";
import { IncomeExpenseChart } from "../components/charts/IncomeExpenseChart";
import { CategoryBreakdownList } from "../components/reports/CategoryBreakdownList";
import { CategoryTransactions } from "../components/reports/CategoryTransactions";
import { CurrencySection } from "../components/reports/CurrencySection";
import { ForecastChart } from "../components/charts/ForecastChart";
import { DashboardBudgetSummary } from "../components/budgets/DashboardBudgetSummary";
import {
  useAccountBreakdown,
  useCategoryBreakdown,
  useMonthlySeries,
  useTotals,
  useTransfersSummary,
} from "../hooks/useAnalytics";
import { useForecast, useRecurringSeries } from "../hooks/useRecurring";
import { useAccounts } from "../hooks/useAccounts";
import { useDashboardPeriod } from "../state/dashboardPeriod";
import { formatDate, formatMoney } from "../lib/format";
import { AccountTypeBadge } from "../components/ui/AccountTypeBadge";
import { useI18n } from "../i18n/useI18n";
import type { MessageKey } from "../i18n/core";
import type { CategoryBreakdownItem, MonthlyPoint } from "../types";
import { MonthTransactions } from "../components/reports/MonthTransactions";

const INTERVALS = new Set(["weekly", "monthly", "quarterly", "yearly"]);

/** The start page: totals, the course over time, spending per category (each
 * opening its bookings), accounts, transfers, recurring payments and the
 * forecast — for the chosen period and account, which are remembered. */
export function Overview() {
  const { t, tn } = useI18n();
  const { range, accountId, setRange, setAccountId } = useDashboardPeriod();
  const { data: accountList } = useAccounts();
  // a saved filter on an account that is archived or gone would filter silently
  useEffect(() => {
    if (accountList && accountId !== undefined && !accountList.some((a) => a.id === accountId)) setAccountId(undefined);
  }, [accountList, accountId, setAccountId]);
  const query = {
    account_id: accountId ? String(accountId) : undefined,
    start: range.start,
    end: range.end,
  };

  const totals = useTotals(query);
  const monthly = useMonthlySeries(query);
  const categories = useCategoryBreakdown(query);
  const accounts = useAccountBreakdown(query);
  const transfers = useTransfersSummary(query);
  const recurring = useRecurringSeries();
  const forecast = useForecast(3);

  const [selected, setSelected] = useState<{ category: string; currency: string } | null>(null);
  const [selectedMonth, setSelectedMonth] = useState<MonthlyPoint | null>(null);

  const hasData = (totals.data?.transaction_count ?? 0) > 0;
  // the chosen month, with its current figures — gone when the period no longer has it
  const shownMonth = selectedMonth ? monthly.data?.find((p) => p.month === selectedMonth.month) ?? null : null;

  // Spending per category; choosing one lists its transactions right below.
  function renderCategories(items: CategoryBreakdownItem[], currency: string, title: string) {
    const current = selected?.currency === currency && items.some((c) => c.category === selected.category)
      ? selected.category
      : null;
    return (
      <>
        <Card className="p-5">
          <h2 className="text-sm font-semibold text-ink mb-1">{title}</h2>
          {items.length > 0 ? (
            <CategoryBreakdownList
              data={items}
              currency={currency}
              selected={current}
              onSelect={(category) => setSelected(category ? { category, currency } : null)}
            />
          ) : (
            <EmptyState title={t("stats.noExpenses")} />
          )}
        </Card>
        {current && (
          <CategoryTransactions
            category={current}
            currency={currency}
            accountId={accountId}
            start={range.start}
            end={range.end}
            onClose={() => setSelected(null)}
          />
        )}
      </>
    );
  }

  return (
    <div>
      <PageHeader title={t("dash.title")} subtitle={t("dash.subtitle")} />
      <div className="p-8 space-y-6">
        <Card className="p-4 flex flex-wrap items-center gap-3">
          <DateRangeSelector range={range} onChange={setRange} />
          <select
            aria-label={t("col.account")}
            className="text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink"
            value={accountId ?? ""}
            onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : undefined)}
          >
            <option value="">{t("tx.allAccounts")}</option>
            {(accountList ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </Card>

        {totals.isError ? (
          <Card>
            <ErrorState error={totals.error} onRetry={() => totals.refetch()} />
          </Card>
        ) : !totals.isLoading && !hasData ? (
          <Card>
            <EmptyState
              title={range.start || range.end || accountId ? t("dash.noTxPeriod") : t("dash.noTx")}
              description={range.start || range.end || accountId ? t("dash.otherPeriod") : t("dash.getStarted")}
            />
          </Card>
        ) : (
          <>
            {totals.data?.is_mixed_currency ? (
              <>
                <Card className="p-4">
                  <Badge tone="warning">{t("stats.multiCurrency")}</Badge>{" "}
                  <span className="ml-2 text-sm text-ink-muted">{t("stats.multiCurrencyBody")}</span>
                </Card>
                {(totals.data.by_currency ?? []).map((c) => (
                  <CurrencySection
                    key={c.currency}
                    currency={c.currency}
                    totals={c}
                    monthly={monthly.data ?? []}
                    categories={categories.data ?? []}
                    renderCategories={(items, currency) =>
                      renderCategories(items, currency, t("stats.byCategoryCur", { currency }))
                    }
                  />
                ))}
              </>
            ) : (
              <>
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                  <StatCard label="stats.income" value={totals.data?.income_minor} currency={totals.data?.currency} tone="income" />
                  <StatCard label="stats.expenses" value={totals.data?.expenses_minor} currency={totals.data?.currency} tone="expense" />
                  <StatCard label="stats.net" value={totals.data?.net_minor} currency={totals.data?.currency} tone="neutral" />
                  <StatCard label="stats.transactionsCounted" value={totals.data?.transaction_count} tone="neutral" isCount />
                </div>

                <Card className="p-5">
                  <h2 className="text-sm font-semibold text-ink mb-4">{t("stats.overTime")}</h2>
                  {monthly.data && monthly.data.length > 0 ? (
                    <>
                      <IncomeExpenseChart
                        data={monthly.data}
                        currency={totals.data?.currency ?? "EUR"}
                        selectedMonth={selectedMonth?.month}
                        onSelectMonth={(month) =>
                          setSelectedMonth(
                            selectedMonth?.month === month ? null : monthly.data?.find((p) => p.month === month) ?? null
                          )
                        }
                      />
                      <p className="text-xs text-ink-faint mt-2">{t("reports.monthClickHint")}</p>
                    </>
                  ) : (
                    <EmptyState title={t("stats.notEnough")} />
                  )}
                </Card>

                {shownMonth && (
                  <MonthTransactions
                    point={shownMonth}
                    currency={totals.data?.currency ?? "EUR"}
                    accountId={accountId}
                    rangeStart={range.start}
                    rangeEnd={range.end}
                    onClose={() => setSelectedMonth(null)}
                  />
                )}

                {renderCategories(categories.data ?? [], totals.data?.currency ?? "EUR", t("stats.byCategory"))}
              </>
            )}

            <DashboardBudgetSummary />

            <Card>
              <div className="px-5 py-4 border-b border-border">
                <h2 className="text-sm font-semibold text-ink">{t("reports.accountBreakdown")}</h2>
              </div>
              {accounts.data && accounts.data.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-ink-muted text-xs">
                      <tr className="border-b border-border">
                        <th className="text-left font-medium px-5 py-2">{t("col.account")}</th>
                        <th className="text-left font-medium px-5 py-2">{t("col.type")}</th>
                        <th className="text-right font-medium px-5 py-2">{t("stats.income")}</th>
                        <th className="text-right font-medium px-5 py-2">{t("stats.expenses")}</th>
                        <th className="text-right font-medium px-5 py-2">{t("reports.net")}</th>
                        <th className="text-right font-medium px-5 py-2">{t("stats.transactions")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {accounts.data.map((a) => (
                        <tr key={a.account_id} className="border-b border-border last:border-0">
                          <td className="px-5 py-2.5 text-ink">{a.account_name}</td>
                          <td className="px-5 py-2.5">
                            <AccountTypeBadge type={a.account_type} />
                          </td>
                          <td className="px-5 py-2.5 text-right tabular-nums text-income">
                            {formatMoney(a.income_minor, a.currency)}
                          </td>
                          <td className="px-5 py-2.5 text-right tabular-nums text-expense">
                            {formatMoney(a.expenses_minor, a.currency)}
                          </td>
                          <td className="px-5 py-2.5 text-right tabular-nums text-ink font-medium">
                            {formatMoney(a.net_minor, a.currency)}
                          </td>
                          <td className="px-5 py-2.5 text-right tabular-nums text-ink-muted">
                            {a.transaction_count}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {accounts.data.some((a) => a.account_type === "credit_card") && (
                    <p className="px-5 py-3 border-t border-border text-xs text-ink-muted">{t("reports.cardRowsHint")}</p>
                  )}
                </div>
              ) : (
                <div className="px-5 py-6">
                  <EmptyState title={t("reports.noActivity")} />
                </div>
              )}
            </Card>

            {transfers.data && transfers.data.transfer_count > 0 && (
              <Card className="p-4">
                {transfers.data.is_mixed_currency ? (
                  <div>
                    <div className="text-sm text-ink">
                      <Badge tone="neutral">{t("reports.transfers")}</Badge>{" "}
                      <span className="ml-2">
                        {t("reports.movedMixed", {
                          amounts: (transfers.data.by_currency ?? [])
                            .map((c) => `${formatMoney(c.total_transferred_minor, c.currency)} (${c.transfer_count})`)
                            .join(", "),
                        })}
                      </span>
                    </div>
                    <p className="text-xs text-ink-muted mt-1">{t("reports.transfersHint")}</p>
                  </div>
                ) : (
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-sm text-ink">
                        <Badge tone="neutral">{t("reports.transfers")}</Badge>{" "}
                        <span className="ml-2">
                          {tn("reports.moved", transfers.data.transfer_count, {
                            amount: formatMoney(transfers.data.total_transferred_minor ?? 0, transfers.data.currency ?? "EUR"),
                          })}
                        </span>
                      </div>
                      <p className="text-xs text-ink-muted mt-1">{t("reports.transfersHint")}</p>
                    </div>
                  </div>
                )}
              </Card>
            )}

            {recurring.data && recurring.data.series.length > 0 && (
              <Card>
                <div className="px-5 py-4 border-b border-border">
                  <h2 className="text-sm font-semibold text-ink">{t("reports.recurring")}</h2>
                  <p className="text-xs text-ink-muted mt-0.5">
                    {t("reports.recurringHint")}
                  </p>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-ink-muted text-xs">
                      <tr className="border-b border-border">
                        <th className="text-left font-medium px-5 py-2">{t("reports.merchantDesc")}</th>
                        <th className="text-left font-medium px-5 py-2">{t("reports.interval")}</th>
                        <th className="text-right font-medium px-5 py-2">{t("reports.lastAmount")}</th>
                        <th className="text-left font-medium px-5 py-2">{t("reports.nextExpected")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recurring.data.series.map((s) => (
                        <tr
                          key={`${s.key}-${s.sign}-${s.currency}`}
                          className={`border-b border-border last:border-0 ${s.is_active ? "" : "opacity-50"}`}
                        >
                          <td className="px-5 py-2.5 text-ink">
                          {s.label || s.key}
                            {!s.is_active && (
                              <span className="ml-2 normal-case text-xs text-ink-faint">{t("reports.inactive")}</span>
                            )}
                          </td>
                          <td className="px-5 py-2.5">
                            <Badge tone="neutral">{INTERVALS.has(s.interval) ? t(`interval.${s.interval}` as MessageKey) : s.interval}</Badge>
                          </td>
                          <td
                            className={`px-5 py-2.5 text-right tabular-nums ${s.sign === "income" ? "text-income" : "text-expense"}`}
                          >
                            {formatMoney(s.last_amount_minor, s.currency)}
                          </td>
                          <td className="px-5 py-2.5 text-ink-muted">
                            {s.is_active ? formatDate(s.next_expected_date) : t("reports.lastOn", { date: formatDate(s.last_date) })}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}

            <Card className="p-5">
              <h2 className="text-sm font-semibold text-ink mb-1">{t("reports.forecast")}</h2>
              <p className="text-xs text-ink-muted mb-4">
                {t("reports.forecastHint")}
              </p>
              {forecast.data && forecast.data.points.length > 0 ? (
                // One chart per currency — amounts in different currencies are never added up.
                <div className="space-y-5">
                  {[...new Set(forecast.data.points.map((p) => p.currency))].map((currency, _i, all) => (
                    <div key={currency}>
                      {all.length > 1 && <div className="text-xs font-medium text-ink-muted mb-1">{currency}</div>}
                      <ForecastChart
                        data={forecast.data!.points.filter((p) => p.currency === currency)}
                        currency={currency}
                      />
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title={t("stats.notEnough")} />
              )}
            </Card>
          </>
        )}
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  currency,
  tone,
  isCount,
}: {
  label: MessageKey;
  value: number | null | undefined;
  currency?: string | null;
  tone: "income" | "expense" | "neutral";
  isCount?: boolean;
}) {
  const { t } = useI18n();
  const toneClass = tone === "income" ? "text-income" : tone === "expense" ? "text-expense" : "text-ink";
  return (
    <Card className="p-5">
      <div className="text-xs font-medium text-ink-muted uppercase tracking-wide">{t(label)}</div>
      <div className={`text-2xl font-semibold mt-2 tabular-nums ${toneClass}`}>
        {value === undefined || value === null ? "—" : isCount ? value : formatMoney(value, currency ?? "EUR")}
      </div>
    </Card>
  );
}
