import { useState } from "react";
import { useI18n } from "../../i18n/useI18n";
import { AccountTypeBadge } from "../ui/AccountTypeBadge";
import { Badge, Button } from "../ui";
import { OpeningBalanceForm } from "./OpeningBalanceForm";
import { useUpdateAccount } from "../../hooks/useAccounts";
import { formatAccountBalance } from "../../lib/accountBalance";
import { formatDate, formatMoney } from "../../lib/format";
import { CURRENCIES } from "../../lib/currencies";
import type { Account } from "../../types";

export function AccountRow({ account }: { account: Account }) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [showBalanceDetail, setShowBalanceDetail] = useState(false);
  const [name, setName] = useState(account.name);
  const [currency, setCurrency] = useState(account.currency);
  const [iban, setIban] = useState(account.iban ?? "");
  const update = useUpdateAccount();
  const currencies = CURRENCIES.includes(account.currency) ? CURRENCIES : [account.currency, ...CURRENCIES];

  function save() {
    if (!name.trim()) return;
    update.mutate(
      { id: account.id, patch: { name: name.trim(), currency, iban: iban.trim() || null } },
      { onSuccess: () => setEditing(false) }
    );
  }

  function cancel() {
    setName(account.name);
    setCurrency(account.currency);
    setIban(account.iban ?? "");
    update.reset();
    setEditing(false);
  }

  function toggleArchive() {
    update.reset();
    update.mutate({ id: account.id, patch: { is_archived: !account.is_archived } });
  }

  const balance = formatAccountBalance(account.current_balance_minor, account.account_type, account.currency);
  const balanceToneClass =
    balance.tone === "income" ? "text-income" : balance.tone === "expense" ? "text-expense" : "text-ink-muted";

  return (
    <>
      <tr className={`border-b border-border last:border-0 ${account.is_archived ? "opacity-60" : ""}`}>
        <td className="px-5 py-3">
          {editing ? (
            <div className="space-y-1.5">
              <input
                onKeyDown={(e) => {
                  if (e.key === "Enter") save();
                  if (e.key === "Escape") cancel();
                }}
                className="text-sm border border-border-strong rounded px-2 py-1 bg-surface text-ink w-56 block"
                value={name}
                onChange={(e) => setName(e.target.value)}
                aria-label={t("accounts.nameLabel")}
                autoFocus
              />
              <input
                onKeyDown={(e) => {
                  if (e.key === "Enter") save();
                  if (e.key === "Escape") cancel();
                }}
                className="text-xs border border-border-strong rounded px-2 py-1 bg-surface text-ink w-56 block font-mono"
                value={iban}
                onChange={(e) => setIban(e.target.value)}
                placeholder={t("accounts.ibanPlaceholder")}
                aria-label={t("accounts.ibanLabel")}
              />
              {update.isError && <div className="text-xs text-danger max-w-56">{(update.error as Error).message}</div>}
            </div>
          ) : (
            <div>
              <span className="text-sm font-medium text-ink">{account.name}</span>{" "}
              {account.is_archived && <Badge tone="neutral">{t("accounts.archived")}</Badge>}
              {account.iban && <div className="text-[11px] text-ink-faint font-mono mt-0.5">{account.iban}</div>}
            </div>
          )}
        </td>
        <td className="px-5 py-3">
          <AccountTypeBadge type={account.account_type} />
        </td>
        <td className="px-5 py-3">
          {editing ? (
            <select
              className="text-sm border border-border-strong rounded px-2 py-1 bg-surface text-ink"
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
            >
              {currencies.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          ) : (
            <span className="text-sm text-ink-muted">{account.currency}</span>
          )}
        </td>
        <td className="px-5 py-3 text-right text-sm tabular-nums text-ink-muted">{account.transaction_count}</td>
        <td className="px-5 py-3 text-right">
          <button
            type="button"
            onClick={() => setShowBalanceDetail((v) => !v)}
            className="text-right w-full"
          >
            <div className={`text-sm font-medium tabular-nums ${balanceToneClass}`}>{balance.value}</div>
            <div className="text-[11px] text-ink-faint mt-0.5 underline underline-offset-2">{t(balance.labelKey)}</div>
          </button>
        </td>
        <td className="px-5 py-3 text-right">
          {editing ? (
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={cancel} className="!px-2 !py-1 text-xs">
                {t("common.cancel")}
              </Button>
              <Button variant="primary" onClick={save} disabled={update.isPending} className="!px-2 !py-1 text-xs">
                {t("common.save")}
              </Button>
            </div>
          ) : (
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setEditing(true)} className="!px-2 !py-1 text-xs">
                {t("common.edit")}
              </Button>
              <Button variant="ghost" onClick={toggleArchive} disabled={update.isPending} className="!px-2 !py-1 text-xs">
                {account.is_archived ? t("accounts.unarchive") : t("accounts.archive")}
              </Button>
            </div>
          )}
          {/* (while editing, the error stands under the fields) */}
          {!editing && update.isError && (
            <div role="alert" className="mt-1 text-xs text-danger text-right">{(update.error as Error).message}</div>
          )}
        </td>
      </tr>
      {showBalanceDetail && (
        <tr className="border-b border-border last:border-0 bg-surface-sunken/50">
          <td colSpan={6} className="px-5 py-4">
            <div className="grid grid-cols-3 gap-6 mb-4 text-sm">
              <div>
                <div className="text-xs text-ink-muted">{t("accounts.balanceFromImports")}</div>
                <div className="tabular-nums text-ink font-medium mt-0.5">
                  {formatMoney(account.transactions_balance_minor, account.currency)}
                </div>
              </div>
              <div>
                <div className="text-xs text-ink-muted">{t("accounts.openingBalance")}</div>
                <div className="tabular-nums text-ink font-medium mt-0.5">
                  {account.opening_balance_minor !== null
                    ? t("accounts.openingAsOf", {
                        amount: formatMoney(account.opening_balance_minor, account.currency),
                        date: formatDate(account.opening_balance_date!),
                      })
                    : t("common.notSet")}
                </div>
              </div>
              <div>
                <div className="text-xs text-ink-muted">{t("accounts.currentBalance")}</div>
                <div className={`tabular-nums font-semibold mt-0.5 ${balanceToneClass}`}>{balance.value}</div>
              </div>
            </div>
            <p className="text-[11px] text-ink-faint mb-3 max-w-lg">{t("accounts.openingHelp")}</p>
            <OpeningBalanceForm account={account} />
          </td>
        </tr>
      )}
    </>
  );
}
