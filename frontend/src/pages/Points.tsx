import { useId, useState } from "react";
import clsx from "clsx";
import { Card, EmptyState, ErrorState, PageHeader } from "../components/ui";
import { PointsChart } from "../components/charts/PointsChart";
import { usePoints, useUpdatePointsProgram } from "../hooks/usePoints";
import { formatDate, formatMoney, formatSignedMoney, getFormatLocale } from "../lib/format";
import { useI18n } from "../i18n/useI18n";
import type { PointsProgram } from "../types";

/** Bonus points and miles, as the card statements print them (see backend
 * app/importers/pdf_layouts/points.py): standing and its worth, what was
 * earned and redeemed per month, the effective cashback, where the points
 * came from. */
export function Points() {
  const { t } = useI18n();
  const { data, isLoading, isError, error, refetch } = usePoints();
  return (
    <div>
      <PageHeader title={t("points.title")} subtitle={t("points.subtitle")} />
      <div className="p-8 space-y-6">
        {isError && (
          <Card>
            <ErrorState error={error} onRetry={() => refetch()} />
          </Card>
        )}
        {!isLoading && data?.length === 0 && (
          <Card>
            <EmptyState title={t("points.emptyTitle")} description={t("points.emptyBody")} />
          </Card>
        )}
        {data && data.length > 0 && <Programs programs={data} />}
        {data && data.length > 0 && <p className="text-xs text-ink-muted max-w-3xl">{t("points.missingHint")}</p>}
      </div>
    </div>
  );
}

/** One tile per program (standing and worth), the chosen one in detail below. */
function Programs({ programs }: { programs: PointsProgram[] }) {
  const { t } = useI18n();
  const number = new Intl.NumberFormat(getFormatLocale());
  const [chosenId, setChosenId] = useState<number>(programs[0].id);
  const chosen = programs.find((p) => p.id === chosenId) ?? programs[0];
  const total = programs.reduce((sum, p) => sum + p.balance_value_minor, 0);
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" role="tablist" aria-label={t("points.programs")}>
        {programs.map((p) => (
          <button
            key={p.id}
            type="button"
            role="tab"
            aria-selected={p.id === chosen.id}
            onClick={() => setChosenId(p.id)}
            className={clsx(
              "text-left rounded-lg border bg-surface px-4 py-3 transition-colors",
              p.id === chosen.id ? "border-accent ring-1 ring-accent" : "border-border hover:border-accent/60"
            )}
          >
            <div className="text-xs text-ink-muted">{p.name}</div>
            <div className="mt-0.5 text-lg font-semibold text-ink tabular-nums">
              {number.format(p.balance)} <span className="text-sm font-normal text-ink-muted">{p.unit}</span>
            </div>
            <div className="text-xs text-ink-muted tabular-nums">≈ {formatMoney(p.balance_value_minor)}</div>
          </button>
        ))}
        {programs.length > 1 && (
          <div className="rounded-lg border border-dashed border-border px-4 py-3">
            <div className="text-xs text-ink-muted">{t("points.totalValue")}</div>
            <div className="mt-0.5 text-lg font-semibold text-ink tabular-nums">{formatMoney(total)}</div>
          </div>
        )}
      </div>
      <div role="tabpanel">
        <ProgramCard key={chosen.id} program={chosen} />
      </div>
    </>
  );
}

function ProgramCard({ program }: { program: PointsProgram }) {
  const { t } = useI18n();
  const number = new Intl.NumberFormat(getFormatLocale());
  const percent = new Intl.NumberFormat(getFormatLocale(), { maximumFractionDigits: 2 });
  const points = (n: number) => `${number.format(n)} ${program.unit}`;
  return (
    <Card>
      <div className="px-5 py-4 border-b border-border flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">{program.name}</h2>
          <div className="mt-1 text-2xl font-semibold text-ink tabular-nums">
            {points(program.balance)}
            <span className="ml-2 text-base font-normal text-ink-muted">≈ {formatMoney(program.balance_value_minor)}</span>
          </div>
          <div className="text-xs text-ink-faint mt-0.5">
            {program.balance_stated
              ? t("points.balanceStated", { date: formatDate(program.balance_as_of) })
              : t("points.balanceSummed")}
          </div>
        </div>
        <ValueEditor program={program} />
      </div>

      <dl className="grid grid-cols-2 md:grid-cols-4 gap-px bg-border border-b border-border text-sm">
        <Stat label={t("points.earnedThisYear")} value={points(program.earned_this_year)} />
        <Stat label={t("points.redeemedThisYear")} value={points(Math.abs(program.redeemed_this_year))} />
        <Stat label={t("points.earnedTotal")} value={points(program.earned)} />
        <Stat
          label={t("points.cashback")}
          value={program.cashback_percent === null ? "—" : `${percent.format(program.cashback_percent)} %`}
          hint={t("points.cashbackHint")}
        />
      </dl>

      {program.months.length > 1 && (
        <div className="px-5 py-4 border-b border-border">
          <h3 className="text-xs font-medium text-ink-muted mb-2">{t("points.perMonth")}</h3>
          <PointsChart months={program.months} />
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-px bg-border">
        <section className="bg-surface px-5 py-4">
          <h3 className="text-xs font-medium text-ink-muted mb-2">{t("points.byMerchant")}</h3>
          {program.merchants.length === 0 ? (
            <p className="text-xs text-ink-faint">{t("points.noMerchants")}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs text-ink-muted">
                  <tr>
                    <th className="text-left font-medium py-1">{t("col.merchant")}</th>
                    <th className="text-right font-medium py-1">{t("points.bookings")}</th>
                    <th className="text-right font-medium py-1">{t("points.points")}</th>
                    <th className="text-right font-medium py-1">{t("points.perEuro")}</th>
                  </tr>
                </thead>
                <tbody>
                  {program.merchants.map((m) => (
                    <tr key={m.merchant} className="border-t border-border">
                      <td className="py-1.5 text-ink truncate max-w-[220px]">{m.merchant}</td>
                      <td className="py-1.5 text-right tabular-nums text-ink-muted">{m.bookings}</td>
                      <td className="py-1.5 text-right tabular-nums text-ink">{number.format(m.points)}</td>
                      <td className="py-1.5 text-right tabular-nums text-ink-muted">
                        {m.spent_minor > 0 ? percent.format((m.points * 100) / m.spent_minor) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <section className="bg-surface px-5 py-4">
          <h3 className="text-xs font-medium text-ink-muted mb-2">{t("points.redemptions")}</h3>
          {program.redemptions.length === 0 ? (
            <p className="text-xs text-ink-faint">{t("points.noRedemptions")}</p>
          ) : (
            <ul className="text-sm divide-y divide-border">
              {program.redemptions.map((r, i) => (
                <li key={i} className="flex justify-between gap-3 py-1.5">
                  <span className="text-ink-muted">{formatDate(r.date)}</span>
                  <span className="tabular-nums text-ink">
                    {points(r.points)}
                    {r.value_minor !== null && <span className="text-ink-muted"> · {formatMoney(r.value_minor)}</span>}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {program.bookings.length > 0 && (
        <div className="px-5 py-4 border-t border-border">
          <h3 className="text-xs font-medium text-ink-muted mb-2">{t("points.latestBookings")}</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <tbody>
                {program.bookings.map((b) => (
                  <tr key={b.transaction_id} className="border-t border-border first:border-0">
                    <td className="py-1.5 text-ink-muted whitespace-nowrap pr-4">{formatDate(b.date)}</td>
                    <td className="py-1.5 text-ink truncate max-w-[320px]">{b.merchant}</td>
                    <td className={`py-1.5 text-right tabular-nums whitespace-nowrap ${b.amount_minor < 0 ? "text-expense" : "text-income"}`}>
                      {formatSignedMoney(b.amount_minor, b.currency)}
                    </td>
                    <td className="py-1.5 pl-4 text-right tabular-nums whitespace-nowrap text-accent-strong">
                      {b.points > 0 ? "+" : ""}
                      {number.format(b.points)}
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

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="bg-surface px-5 py-3" title={hint}>
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className="mt-0.5 font-medium text-ink tabular-nums">{value}</dd>
    </div>
  );
}

/** What one point is worth, in cents — from the statement, or set here. */
function ValueEditor({ program }: { program: PointsProgram }) {
  const { t } = useI18n();
  const id = useId();
  const update = useUpdatePointsProgram();
  const shown = new Intl.NumberFormat(getFormatLocale(), { maximumFractionDigits: 2, useGrouping: false }).format(
    program.value_per_100 / 100
  );
  const [text, setText] = useState(shown);
  const [prev, setPrev] = useState(shown);
  if (prev !== shown) {
    setPrev(shown);
    setText(shown);
  }
  function save() {
    const cents = Number(text.trim().replace(",", "."));
    // an emptied field is no answer (0 has to be typed)
    if (!text.trim() || !Number.isFinite(cents) || cents < 0 || cents > 1000) {
      setText(shown);
      return;
    }
    const value = Math.round(cents * 100);
    if (value !== program.value_per_100) update.mutate({ id: program.id, value_per_100: value });
  }
  return (
    <div className="text-xs text-ink-muted">
      <label htmlFor={id} className="block mb-1">
        {t("points.valuePerPoint")}
      </label>
      <div className="flex items-center gap-1.5">
        <input
          id={id}
          inputMode="decimal"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={save}
          onKeyDown={(e) => e.key === "Enter" && save()}
          className="w-16 rounded border border-border bg-surface px-2 py-1 text-right text-sm text-ink tabular-nums"
        />
        <span>{t("points.cent")}</span>
      </div>
      {update.error && <p className="text-danger mt-1">{(update.error as Error).message}</p>}
    </div>
  );
}
