import { Badge, Button, Card } from "../ui";
import { formatDate, formatSignedMoney } from "../../lib/format";
import { useClearBankPayment, useFindBankPayment, useSelectBankPayment } from "../../hooks/useReconciliation";
import type { ReconciliationDetail } from "../../types";
import { useI18n } from "../../i18n/useI18n";

export function BankPaymentPanel({ detail }: { detail: ReconciliationDetail }) {
  const { t } = useI18n();
  const select = useSelectBankPayment(detail.statement_id);
  const clear = useClearBankPayment(detail.statement_id);
  const find = useFindBankPayment(detail.statement_id);
  const { bank_payment } = detail;
  const busy = select.isPending || clear.isPending || find.isPending;
  const error = (select.error ?? clear.error ?? find.error) as Error | null;

  return (
    <Card>
      <div className="px-5 py-4 border-b border-border">
        <h2 className="text-sm font-semibold text-ink">{t("recon.bankPayment")}</h2>
        <p className="text-xs text-ink-muted mt-0.5">{t("recon.bankPaymentHint")}</p>
      </div>

      {bank_payment.status === "matched" && bank_payment.transaction && (
        <div className="px-5 py-4 space-y-2">
          <Row label={t("recon.date")} value={formatDate(bank_payment.transaction.transaction_date)} />
          <Row label={t("recon.description")} value={bank_payment.transaction.normalized_description} />
          <Row
            label={t("recon.amount")}
            value={formatSignedMoney(bank_payment.transaction.amount_minor, bank_payment.transaction.currency)}
          />
          <Row label={t("recon.account")} value={bank_payment.transaction.account_name} />
          {bank_payment.transaction.source_filename && (
            <Row label={t("recon.sourceFile")} value={bank_payment.transaction.source_filename} />
          )}
          <div className="pt-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Badge tone="neutral">{t("recon.settlement")}</Badge>
              <span className="text-xs text-ink-faint">{t("recon.notCountedTwice")}</span>
            </div>
            <Button variant="ghost" className="text-xs" disabled={busy} onClick={() => clear.mutate()}>
              {clear.isPending ? t("recon.unlinking") : t("recon.wrongPayment")}
            </Button>
          </div>
        </div>
      )}

      {bank_payment.status === "not_found" && (
        <div className="px-5 py-6 text-center space-y-3">
          <div className="text-sm font-medium text-ink">{t("recon.paymentNotFound")}</div>
          <p className="text-sm text-ink-muted max-w-md mx-auto">
            {t("recon.paymentNotFoundBody")}
          </p>
          <Button variant="secondary" disabled={busy} onClick={() => find.mutate()}>
            {find.isPending ? t("recon.searching") : t("recon.searchAgain")}
          </Button>
        </div>
      )}

      {bank_payment.status === "suggested" && (
        <div className="px-5 py-4">
          <p className="text-sm text-ink-muted mb-3">
            {bank_payment.recommended_transaction_id !== null
              ? t("recon.oneExact")
              : t("recon.closeCandidates")}
          </p>
          <div className="space-y-2">
            {bank_payment.candidates.map((c) => {
              const recommended = c.id === bank_payment.recommended_transaction_id;
              return (
                <div
                  key={c.id}
                  className={`flex items-center justify-between border rounded-md px-3 py-2.5 ${recommended ? "border-accent bg-accent-soft/40" : "border-border"}`}
                >
                  <div>
                    <div className="text-sm text-ink">
                      {c.normalized_description} {recommended && <Badge tone="accent">{t("recon.exactAmount")}</Badge>}
                    </div>
                    <div className="text-xs text-ink-muted mt-0.5">
                      {formatDate(c.transaction_date)} · {c.account_name} · {formatSignedMoney(c.amount_minor, c.currency)}
                    </div>
                  </div>
                  <Button
                    variant={recommended ? "primary" : "secondary"}
                    disabled={busy}
                    onClick={() => select.mutate(c.id)}
                  >
                    {t("recon.useThis")}
                  </Button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {error && <div className="px-5 pb-4 text-xs text-danger">{error.message}</div>}
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 text-sm">
      <span className="text-ink-muted shrink-0">{label}</span>
      <span className="text-ink font-medium text-right min-w-0 [overflow-wrap:anywhere]">{value}</span>
    </div>
  );
}
