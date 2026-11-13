import { useId, useState } from "react";
import { useI18n } from "../../i18n/useI18n";
import { Button } from "../ui";
import { useCreateAccount } from "../../hooks/useAccounts";
import type { AccountType } from "../../types";
import { CURRENCIES } from "../../lib/currencies";

export function CreateAccountForm({ onDone }: { onDone: () => void }) {
  const { t } = useI18n();
  const ids = useId();
  const [name, setName] = useState("");
  const [accountType, setAccountType] = useState<AccountType>("checking");
  const [currency, setCurrency] = useState("EUR");
  const [iban, setIban] = useState("");
  const create = useCreateAccount();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    create.mutate(
      { name: name.trim(), account_type: accountType, currency, iban: iban.trim() || null },
      {
        onSuccess: () => {
          setName("");
          setAccountType("checking");
          setCurrency("EUR");
          setIban("");
          onDone();
        },
      }
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor={`${ids}-name`} className="text-xs text-ink-muted">{t("accounts.nameLabel")}</label>
        <input
          id={`${ids}-name`}
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("accounts.namePlaceholder")}
          className="text-sm border border-border-strong rounded-md px-2.5 py-2 bg-surface text-ink w-56"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor={`${ids}-type`} className="text-xs text-ink-muted">{t("accounts.typeLabel")}</label>
        <select
          id={`${ids}-type`}
          value={accountType}
          onChange={(e) => setAccountType(e.target.value as AccountType)}
          className="text-sm border border-border-strong rounded-md px-2.5 py-2 bg-surface text-ink"
        >
          <option value="checking">{t("accountType.checking")}</option>
          <option value="savings">{t("accountType.savings")}</option>
          <option value="credit_card">{t("accountType.credit_card")}</option>
          <option value="other">{t("accountType.other")}</option>
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor={`${ids}-currency`} className="text-xs text-ink-muted">{t("accounts.currencyLabel")}</label>
        <select
          id={`${ids}-currency`}
          value={currency}
          onChange={(e) => setCurrency(e.target.value)}
          className="text-sm border border-border-strong rounded-md px-2.5 py-2 bg-surface text-ink"
        >
          {CURRENCIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor={`${ids}-iban`} className="text-xs text-ink-muted">
          {t("accounts.ibanLabel")} <span className="text-ink-faint">{t("accounts.ibanHint")}</span>
        </label>
        <input
          id={`${ids}-iban`}
          type="text"
          value={iban}
          onChange={(e) => setIban(e.target.value)}
          placeholder="DE00 0000 0000 0000 0000 00"
          className="text-sm border border-border-strong rounded-md px-2.5 py-2 bg-surface text-ink w-72 font-mono"
        />
      </div>
      <Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>
        {create.isPending ? t("accounts.creating") : t("accounts.create")}
      </Button>
      {create.isError && <div className="text-xs text-danger w-full">{(create.error as Error).message}</div>}
    </form>
  );
}
