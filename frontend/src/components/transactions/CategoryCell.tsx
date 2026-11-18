import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { categoryLabel, countingOf } from "../../lib/categories";
import { formatMoney } from "../../lib/format";
import { useCategoryNames } from "../../hooks/useCategories";
import { useI18n } from "../../i18n/useI18n";
import type { CountAs, Transaction } from "../../types";

const UNSORTED = new Set(["Other Expense", "Other Income"]);

/** The category of a transaction, changeable with one click: a popover
 * with every category. Choosing one calls `onAssign`; the page decides
 * whether the choice is learned for similar transactions. Money that came
 * in and gets a category of spending is asked about first: a refund of
 * that spending (reimbursed travel costs), or income? */
export function CategoryCell({
  transaction,
  busy,
  onAssign,
}: {
  transaction: Transaction;
  busy: boolean;
  onAssign: (transaction: Transaction, category: string, countAs?: CountAs) => void;
}) {
  const { t } = useI18n();
  const categories = useCategoryNames();
  const [open, setOpen] = useState(false);
  // the category chosen for money that came in: refund or income? (asked in the popover)
  const [asking, setAsking] = useState<string | null>(null);
  const wrapper = useRef<HTMLDivElement>(null);
  const current = transaction.category;
  const unsorted = !current || UNSORTED.has(current);
  const options = current && !categories.includes(current) ? [...categories, current] : categories;

  useEffect(() => {
    if (!open) return;
    // focus the current category (or the first one, or the first answer) for keyboard users
    const el = wrapper.current?.querySelector<HTMLButtonElement>("[data-answer]")
      ?? wrapper.current?.querySelector<HTMLButtonElement>("[aria-pressed='true']")
      ?? wrapper.current?.querySelector<HTMLButtonElement>("[data-option]");
    el?.focus();
    function onPointerDown(e: PointerEvent) {
      if (wrapper.current && !wrapper.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open, asking]);

  function close() {
    setOpen(false);
    setAsking(null);
  }

  function choose(category: string) {
    const counting = countingOf(transaction, category);
    if (counting === "ask") {
      // (also for its current category: that is how one counted as income becomes a refund)
      setAsking(category);
      return;
    }
    close();
    if (category !== current) onAssign(transaction, category, counting === "income" ? "income" : undefined);
  }

  function answer(countAs: CountAs) {
    const category = asking!;
    close();
    if (category !== current || countAs === "refund") onAssign(transaction, category, countAs);
  }

  const name = transaction.merchant ?? transaction.normalized_description;
  return (
    <div
      ref={wrapper}
      className="relative"
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.stopPropagation();
          close();
          wrapper.current?.querySelector<HTMLButtonElement>("[data-trigger]")?.focus();
        }
      }}
    >
      <button
        type="button"
        data-trigger
        disabled={busy}
        aria-haspopup="true"
        aria-expanded={open}
        title={t("tx.changeCategory")}
        aria-label={t("tx.categoryOf", { name, category: categoryLabel(t, current) })}
        onClick={() => (open ? close() : setOpen(true))}
        className={clsx(
          "group inline-flex items-center gap-1 rounded px-1.5 py-0.5 -mx-1.5 text-left hover:bg-surface-sunken",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60",
          unsorted ? "text-warning" : "text-ink-muted"
        )}
      >
        <span>{busy ? t("common.saving") : categoryLabel(t, current)}</span>
        <span aria-hidden className="text-[10px] text-ink-faint opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100">
          ✎
        </span>
      </button>
      {open && asking !== null && (
        <div
          role="group"
          aria-label={t("tx.countAsQuestion", { amount: formatMoney(transaction.amount_minor, transaction.currency) })}
          className="absolute left-0 top-full z-20 mt-1 w-80 rounded-md border border-border bg-surface p-3 shadow-lg space-y-2"
        >
          <p className="text-xs text-ink">
            {t("tx.countAsQuestion", { amount: formatMoney(transaction.amount_minor, transaction.currency) })}
          </p>
          <button
            type="button"
            data-answer
            onClick={() => answer("refund")}
            className="block w-full text-left text-xs rounded px-2 py-1.5 border border-border hover:bg-surface-sunken focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          >
            <span className="font-medium text-ink">{t("tx.countAsRefund", { category: categoryLabel(t, asking) })}</span>
            <span className="block text-ink-muted">{t("tx.countAsRefundHint", { category: categoryLabel(t, asking) })}</span>
          </button>
          <button
            type="button"
            onClick={() => answer("income")}
            className="block w-full text-left text-xs rounded px-2 py-1.5 border border-border hover:bg-surface-sunken focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          >
            <span className="font-medium text-ink">{t("tx.countAsIncome")}</span>
            <span className="block text-ink-muted">{t("tx.countAsIncomeHint")}</span>
          </button>
          <button
            type="button"
            onClick={() => setAsking(null)}
            className="text-xs text-ink-muted underline underline-offset-2"
          >
            {t("tx.countAsBack")}
          </button>
        </div>
      )}
      {open && asking === null && (
        <div
          role="group"
          aria-label={t("tx.chooseCategory")}
          className="absolute left-0 top-full z-20 mt-1 w-80 rounded-md border border-border bg-surface p-2 shadow-lg grid grid-cols-2 gap-1"
        >
          {options.map((category) => (
            <button
              key={category}
              type="button"
              data-option
              aria-pressed={category === current}
              onClick={() => choose(category)}
              className={clsx(
                "text-left text-xs rounded px-2 py-1.5 border focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent",
                category === current
                  ? "border-accent bg-accent-soft text-accent-strong"
                  : "border-transparent text-ink hover:bg-surface-sunken"
              )}
            >
              {categoryLabel(t, category)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
