import { useState } from "react";
import { useI18n } from "../i18n/useI18n";
import { Card, EmptyState, ErrorState, PageHeader, Button } from "../components/ui";
import { CreateAccountForm } from "../components/accounts/CreateAccountForm";
import { AccountRow } from "../components/accounts/AccountRow";
import { RecheckTransfersCard } from "../components/accounts/RecheckTransfersCard";
import { useAccounts } from "../hooks/useAccounts";

export function Accounts() {
  const { t, tn } = useI18n();
  const [showForm, setShowForm] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  // Always load archived accounts too: otherwise an archived account could
  // never be found again to unarchive it.
  const { data: allAccounts, refetch, isError, error } = useAccounts(true);
  const archivedCount = allAccounts?.filter((a) => a.is_archived).length ?? 0;
  const accounts = allAccounts?.filter((a) => showArchived || !a.is_archived) ?? [];

  return (
    <div>
      <PageHeader
        title={t("accounts.title")}
        subtitle={t("accounts.subtitle")}
        actions={
          <Button variant={showForm ? "secondary" : "primary"} onClick={() => setShowForm((v) => !v)}>
            {showForm ? t("common.cancel") : t("accounts.add")}
          </Button>
        }
      />
      <div className="p-8 space-y-6">
        {showForm && (
          <Card className="p-5">
            <CreateAccountForm onDone={() => { setShowForm(false); refetch(); }} />
          </Card>
        )}

        <Card>
          {/* not an empty list: the accounts could not be loaded */}
          {isError && !allAccounts && <ErrorState error={error} onRetry={() => refetch()} />}
          {allAccounts && allAccounts.length === 0 && (
            <EmptyState
              title={t("accounts.emptyTitle")}
              description={t("accounts.emptyBody")}
            />
          )}
          {accounts.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-ink-muted text-xs">
                  <tr className="border-b border-border">
                    <th className="text-left font-medium px-5 py-2.5">{t("accounts.col.name")}</th>
                    <th className="text-left font-medium px-5 py-2.5">{t("accounts.col.type")}</th>
                    <th className="text-left font-medium px-5 py-2.5">{t("accounts.col.currency")}</th>
                    <th className="text-right font-medium px-5 py-2.5">{t("accounts.col.transactions")}</th>
                    <th className="text-right font-medium px-5 py-2.5">{t("accounts.col.balance")}</th>
                    <th className="px-5 py-2.5"></th>
                  </tr>
                </thead>
                <tbody>
                  {accounts.map((a) => (
                    <AccountRow key={a.id} account={a} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {allAccounts && allAccounts.length > 0 && accounts.length === 0 && (
            <div className="px-5 py-6 text-sm text-ink-muted">{t("accounts.allArchived")}</div>
          )}
          {allAccounts && allAccounts.length > 0 && (
            <div className="px-5 py-3 border-t border-border flex items-center justify-between gap-4">
              {archivedCount > 0 ? (
                <label className="flex items-center gap-2 text-xs text-ink-muted shrink-0">
                  <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
                  {tn("accounts.showArchived", archivedCount)}
                </label>
              ) : (
                <span />
              )}
              <span className="text-[11px] text-ink-faint text-right">{t("accounts.balanceNote")}</span>
            </div>
          )}
        </Card>

        <RecheckTransfersCard />
      </div>
    </div>
  );
}
