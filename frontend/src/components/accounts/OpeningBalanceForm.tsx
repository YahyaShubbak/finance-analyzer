import { useId, useState } from "react";
import { useI18n } from "../../i18n/useI18n";
import { Button } from "../ui";
import { useUpdateAccount } from "../../hooks/useAccounts";
import type { Account } from "../../types";

export function OpeningBalanceForm({ account }: { account: Account }) {
  const { t } = useI18n();
  const ids = useId();
  const [amount, setAmount] = useState(
    account.opening_balance_minor !== null ? (account.opening_balance_minor / 100).toFixed(2) : ""
  );
  const [asOfDate, setAsOfDate] = useState(account.opening_balance_date ?? "");
  const update = useUpdateAccount();

  const hasOpeningBalance = account.opening_balance_minor !== null;

  function handleSave() {
    const parsed = Number(amount);
    if (Number.isNaN(parsed) || !asOfDate) return;
    update.mutate({
      id: account.id,
      patch: { opening_balance_minor: Math.round(parsed * 100), opening_balance_date: asOfDate },
    });
  }

  function handleClear() {
    setAmount("");
    setAsOfDate("");
    update.mutate({ id: account.id, patch: { opening_balance_minor: null, opening_balance_date: null } });
  }

  return (
    <div className="flex flex-wrap items-end gap-2">
      <div>
        <label htmlFor={`${ids}-amount`} className="text-xs text-ink-muted block mb-1">{t("accounts.openingAmount", { currency: account.currency })}</label>
        <input
          id={`${ids}-amount`}
          type="number"
          step="0.01"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder="0.00"
          className="text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink w-32"
        />
      </div>
      <div>
        <label htmlFor={`${ids}-date`} className="text-xs text-ink-muted block mb-1">{t("accounts.openingDate")}</label>
        <input
          id={`${ids}-date`}
          type="date"
          value={asOfDate}
          onChange={(e) => setAsOfDate(e.target.value)}
          className="text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink"
        />
      </div>
      <Button
        variant="secondary"
        className="!px-2.5 !py-1.5 text-xs"
        disabled={!amount || !asOfDate || update.isPending}
        onClick={handleSave}
      >
        {t("common.save")}
      </Button>
      {update.isError && <div className="text-xs text-danger w-full">{(update.error as Error).message}</div>}
      {hasOpeningBalance && (
        <Button variant="ghost" className="!px-2.5 !py-1.5 text-xs" onClick={handleClear} disabled={update.isPending}>
          {t("common.clear")}
        </Button>
      )}
    </div>
  );
}
