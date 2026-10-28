import clsx from "clsx";
import { formatMoney, getFormatLocale } from "../../lib/format";

export interface BreakdownBar {
  key: string;
  label: string;
  amount_minor: number;
  /** shown greyed out and left out of the scale and the shares, e.g. "no known place" */
  muted?: boolean;
}

/** Amounts (one currency) as a list of bars, largest first. Every row is a
 * button: choosing one calls onSelect with its key, choosing the selected
 * one again with null. Shares are of the rows that aren't muted. */
export function BreakdownBars({
  items,
  currency,
  selected,
  onSelect,
}: {
  items: BreakdownBar[];
  currency: string;
  selected: string | null;
  onSelect: (key: string | null) => void;
}) {
  const counted = items.some((d) => !d.muted) ? items.filter((d) => !d.muted) : items;
  const sum = counted.reduce((s, d) => s + Math.max(0, d.amount_minor), 0);
  const largest = Math.max(0, ...counted.map((d) => d.amount_minor));
  const percent = new Intl.NumberFormat(getFormatLocale(), { style: "percent", maximumFractionDigits: 0 });

  return (
    <ul className="space-y-0.5">
      {items.map((d) => {
        const active = d.key === selected;
        return (
          <li key={d.key}>
            <button
              type="button"
              aria-pressed={active}
              onClick={() => onSelect(active ? null : d.key)}
              className={clsx(
                "w-full grid grid-cols-[minmax(0,11rem)_minmax(0,1fr)_7.5rem_3rem] items-center gap-3 rounded-md px-2 py-1.5 text-left text-sm",
                "hover:bg-surface-sunken focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent",
                active && "bg-accent-soft hover:bg-accent-soft"
              )}
            >
              <span
                className={clsx(
                  "truncate",
                  active ? "font-medium text-accent-strong" : d.muted ? "text-ink-muted" : "text-ink"
                )}
              >
                {d.label}
              </span>
              <span className="h-2.5 rounded-full bg-surface-sunken overflow-hidden" aria-hidden>
                <span
                  className={clsx(
                    "block h-full rounded-full",
                    active ? "bg-accent-strong" : d.muted ? "bg-border-strong" : "bg-accent"
                  )}
                  style={{ width: `${largest > 0 && d.amount_minor > 0 ? Math.min(100, Math.max(1, (d.amount_minor / largest) * 100)) : 0}%` }}
                />
              </span>
              {/* below zero: more refunds than spending in this period */}
              <span className={clsx("tabular-nums text-right", d.amount_minor < 0 ? "text-income" : "text-ink")}>
                {formatMoney(d.amount_minor, currency)}
              </span>
              <span className="tabular-nums text-xs text-ink-muted text-right">
                {sum > 0 && d.amount_minor > 0 && !(d.muted && counted !== items) ? percent.format(d.amount_minor / sum) : ""}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
