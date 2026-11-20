import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { addCashEntry, countCash, getWallet } from "../../api/accounts";
import { useCategories } from "../../hooks/useCategories";
import { invalidateTransactionDependentQueries } from "../../hooks/invalidation";
import { useI18n } from "../../i18n/useI18n";
import { categoryLabel } from "../../lib/categories";
import { formatMoney, toLocalIsoDate } from "../../lib/format";
import { Button } from "../ui";
import type { Account } from "../../types";

const field = "text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink";

/** A cash account: book what was paid or taken in cash, and count the wallet. */
export function CashEntryForm({ account }: { account: Account }) {
  const { t } = useI18n();
  const ids = useId();
  const qc = useQueryClient();
  const [today] = useState(() => toLocalIsoDate(new Date()));
  const wallet = useQuery({ queryKey: ["wallet", account.id], queryFn: () => getWallet(account.id) });
  const categories = useCategories();
  const [direction, setDirection] = useState<"out" | "in">("out");
  const [amount, setAmount] = useState("");
  const [day, setDay] = useState(today);
  const [category, setCategory] = useState("");
  const [note, setNote] = useState("");
  const [counted, setCounted] = useState("");

  // the wallet, the accounts' balances and every figure built from bookings
  const done = () => invalidateTransactionDependentQueries(qc);
  const add = useMutation({
    mutationFn: () => {
      const minor = Math.round(Math.abs(Number(amount)) * 100);
      return addCashEntry(account.id, {
        transaction_date: day, amount_minor: direction === "out" ? -minor : minor, category, note: note || undefined,
      });
    },
    onSuccess: () => {
      setAmount("");
      setNote("");
      done();
    },
  });
  const count = useMutation({
    mutationFn: () => countCash(account.id, { counted_on: today, counted_minor: Math.round(Number(counted) * 100) }),
    onSuccess: () => {
      setCounted("");
      done();
    },
  });
  const valid = Number(amount) > 0 && category !== "" && day !== "";

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-ink">{t("cash.title")}</h3>
        <p className="text-[11px] text-ink-faint max-w-lg">{t("cash.hint")}</p>
        {wallet.data && (
          <p className="text-xs text-ink-muted mt-1">
            {t("cash.balance", {
              balance: formatMoney(wallet.data.balance_minor, account.currency),
              withdrawn: formatMoney(wallet.data.withdrawn_minor, account.currency),
            })}
          </p>
        )}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <select aria-label={t("cash.direction")} className={field} value={direction}
                onChange={(e) => setDirection(e.target.value as "out" | "in")}>
          <option value="out">{t("cash.out")}</option>
          <option value="in">{t("cash.in")}</option>
        </select>
        <div>
          <label htmlFor={`${ids}-amount`} className="text-xs text-ink-muted block mb-1">{t("cash.amount", { currency: account.currency })}</label>
          <input id={`${ids}-amount`} type="number" step="0.01" min="0" value={amount} placeholder="0.00"
                 onChange={(e) => setAmount(e.target.value)} className={`${field} w-28`} />
        </div>
        <div>
          <label htmlFor={`${ids}-date`} className="text-xs text-ink-muted block mb-1">{t("cash.date")}</label>
          <input id={`${ids}-date`} type="date" value={day} onChange={(e) => setDay(e.target.value)} className={field} />
        </div>
        <div>
          <label htmlFor={`${ids}-cat`} className="text-xs text-ink-muted block mb-1">{t("cash.category")}</label>
          <select id={`${ids}-cat`} className={field} value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">{t("cash.chooseCategory")}</option>
            {(categories.data ?? []).map((c) => (
              <option key={c.name} value={c.name}>{categoryLabel(t, c.name)}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={`${ids}-note`} className="text-xs text-ink-muted block mb-1">{t("cash.note")}</label>
          <input id={`${ids}-note`} value={note} maxLength={200} onChange={(e) => setNote(e.target.value)}
                 placeholder={t("cash.notePlaceholder")} className={`${field} w-48`} />
        </div>
        <Button variant="secondary" className="!px-2.5 !py-1.5 text-xs" disabled={!valid || add.isPending}
                onClick={() => add.mutate()}>
          {t("cash.add")}
        </Button>
      </div>
      {add.isError && <p className="text-xs text-danger">{(add.error as Error).message}</p>}
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label htmlFor={`${ids}-count`} className="text-xs text-ink-muted block mb-1">{t("cash.counted", { currency: account.currency })}</label>
          <input id={`${ids}-count`} type="number" step="0.01" min="0" value={counted} placeholder="0.00"
                 onChange={(e) => setCounted(e.target.value)} className={`${field} w-28`} />
        </div>
        <Button variant="secondary" className="!px-2.5 !py-1.5 text-xs" title={t("cash.countHint")}
                disabled={counted === "" || Number(counted) < 0 || count.isPending} onClick={() => count.mutate()}>
          {t("cash.count")}
        </Button>
        <Link to="/transactions" className="text-xs text-accent-strong underline">
          {t("cash.showEntries")}
        </Link>
      </div>
      {count.isError && <p className="text-xs text-danger">{(count.error as Error).message}</p>}
    </div>
  );
}
