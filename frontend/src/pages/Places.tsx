import { useMemo, useState } from "react";
import { Card, EmptyState, PageHeader } from "../components/ui";
import { DateRangeSelector, type DateRange } from "../components/reports/DateRangeSelector";
import { BreakdownBars, type BreakdownBar } from "../components/reports/BreakdownBars";
import { BreakdownTransactions } from "../components/reports/BreakdownTransactions";
import { useLocationBreakdown } from "../hooks/useAnalytics";
import { getLocationTransactions } from "../api/analytics";
import { countryName } from "../lib/places";
import { formatMoney, getFormatLocale } from "../lib/format";
import { useI18n } from "../i18n/useI18n";
import type { LocationBreakdownItem } from "../types";

const ONLINE = "online";
const UNKNOWN = "unknown";
const NO_TOWN = "\u0000no-town"; // never a town's name

interface Country {
  country: string;
  amount_minor: number;
  towns: { city: string | null; amount_minor: number }[];
}

interface CurrencyPlaces {
  currency: string;
  total: number;
  countries: Country[];
  online: number;
  unknown: number;
}

function group(items: LocationBreakdownItem[]): CurrencyPlaces[] {
  const byCurrency = new Map<string, CurrencyPlaces>();
  for (const item of items) {
    let entry = byCurrency.get(item.currency);
    if (!entry) {
      entry = { currency: item.currency, total: 0, countries: [], online: 0, unknown: 0 };
      byCurrency.set(item.currency, entry);
    }
    entry.total += item.amount_minor;
    if (item.online) entry.online += item.amount_minor;
    else if (!item.country) entry.unknown += item.amount_minor;
    else {
      let country = entry.countries.find((c) => c.country === item.country);
      if (!country) {
        country = { country: item.country, amount_minor: 0, towns: [] };
        entry.countries.push(country);
      }
      country.amount_minor += item.amount_minor;
      country.towns.push({ city: item.city, amount_minor: item.amount_minor });
    }
  }
  const result = [...byCurrency.values()];
  for (const entry of result) {
    entry.countries.sort((a, b) => b.amount_minor - a.amount_minor);
    for (const c of entry.countries) c.towns.sort((a, b) => b.amount_minor - a.amount_minor);
  }
  return result.sort((a, b) => b.total - a.total);
}

type Selection = { currency: string; key: string; town: string | null };

/** Spending by country and town, worked out from what the statements say
 * about each payment's place (see backend app/normalization/location.py). */
export function Places() {
  const { t } = useI18n();
  const [range, setRange] = useState<DateRange>({ start: undefined, end: undefined });
  const query = { start: range.start, end: range.end };
  const breakdown = useLocationBreakdown(query);
  const [selected, setSelected] = useState<Selection | null>(null);
  const sections = useMemo(() => group(breakdown.data ?? []), [breakdown.data]);
  const percent = new Intl.NumberFormat(getFormatLocale(), { style: "percent", maximumFractionDigits: 0 });

  return (
    <div>
      <PageHeader title={t("places.title")} subtitle={t("places.subtitle")} />
      <div className="p-8 space-y-6">
        <Card className="p-4">
          <DateRangeSelector range={range} onChange={setRange} />
        </Card>

        {breakdown.isError ? (
          <Card className="p-5 text-sm text-danger">{(breakdown.error as Error).message}</Card>
        ) : !breakdown.isLoading && sections.length === 0 ? (
          <Card>
            <EmptyState title={t("stats.noExpenses")} description={t("reports.emptyBody")} />
          </Card>
        ) : (
          sections.map((section) => {
            const current = selected?.currency === section.currency ? selected : null;
            const country = current && section.countries.find((c) => c.country === current.key);
            const located = section.total - section.unknown;
            const bars: BreakdownBar[] = [
              ...section.countries.map((c) => ({ key: c.country, label: countryName(c.country), amount_minor: c.amount_minor })),
              ...(section.online !== 0 ? [{ key: ONLINE, label: t("places.online"), amount_minor: section.online }] : []),
              ...(section.unknown !== 0
                ? [{ key: UNKNOWN, label: t("places.unknown"), amount_minor: section.unknown, muted: true }]
                : []),
            ];
            const valid = current && bars.some((b) => b.key === current.key) ? current : null;
            return (
              <div key={section.currency} className="space-y-6">
                <Card className="p-5">
                  <h2 className="text-sm font-semibold text-ink mb-1">
                    {sections.length > 1
                      ? t("places.byCountryCur", { currency: section.currency })
                      : t("places.byCountry")}
                  </h2>
                  <p className="text-xs text-ink-muted mb-3">{t("places.hint")}</p>
                  <BreakdownBars
                    items={bars}
                    currency={section.currency}
                    selected={valid?.key ?? null}
                    onSelect={(key) => setSelected(key ? { currency: section.currency, key, town: null } : null)}
                  />
                  <p className="text-xs text-ink-muted mt-4 border-t border-border pt-3">
                    {t("places.coverage", {
                      share: percent.format(section.total > 0 ? located / section.total : 0),
                      amount: formatMoney(located, section.currency),
                    })}{" "}
                    {t("places.sources")}
                  </p>
                </Card>

                {valid && country && country.towns.length > 1 && (
                  <Card className="p-5">
                    <h2 className="text-sm font-semibold text-ink mb-3">
                      {t("places.townsIn", { country: countryName(country.country) })}
                    </h2>
                    <BreakdownBars
                      items={country.towns.map((town) => ({
                        key: town.city ?? NO_TOWN,
                        label: town.city ?? t("places.noTown"),
                        amount_minor: town.amount_minor,
                        muted: town.city === null,
                      }))}
                      currency={section.currency}
                      selected={valid.town}
                      onSelect={(town) => setSelected({ ...valid, town })}
                    />
                  </Card>
                )}

                {valid && (
                  <PlaceTransactions
                    selection={valid}
                    start={range.start}
                    end={range.end}
                    onClose={() => setSelected(null)}
                  />
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function PlaceTransactions({
  selection,
  start,
  end,
  onClose,
}: {
  selection: Selection;
  start?: string;
  end?: string;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const { currency, key, town } = selection;
  const where =
    key === ONLINE
      ? { online: true }
      : key === UNKNOWN
        ? {}
        : town === NO_TOWN
          ? { country: key, no_city: true }
          : town
            ? { country: key, city: town }
            : { country: key };
  const title =
    key === ONLINE
      ? t("places.onlineTransactions")
      : key === UNKNOWN
        ? t("places.unknownTransactions")
        : t("reports.categoryTransactions", {
            category: town && town !== NO_TOWN ? `${town}, ${countryName(key)}` : countryName(key),
          });
  return (
    <BreakdownTransactions
      title={title}
      currency={currency}
      queryKey={["place", currency, key, town, start, end]}
      fetchPage={(page, page_size, view) => getLocationTransactions({ ...view, ...where, currency, start, end, page, page_size })}
      emptyText={t("places.empty")}
      onClose={onClose}
    />
  );
}
