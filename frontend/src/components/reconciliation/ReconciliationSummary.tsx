import { Badge, Card } from "../ui";
import { explanationLabel } from "../../lib/explanationTags";
import { formatMoney } from "../../lib/format";
import type { ReconciliationDetail } from "../../types";
import { useI18n } from "../../i18n/useI18n";

export function ReconciliationSummary({ detail }: { detail: ReconciliationDetail }) {
  const { t } = useI18n();
  const currency = detail.currency;
  const bankAmount =
    detail.bank_payment.status === "matched" && detail.bank_payment.transaction
      ? Math.abs(detail.bank_payment.transaction.amount_minor)
      : null;

  if (detail.status === "reconciled") {
    return (
      <Card className="p-6">
        <div className="grid grid-cols-3 gap-6 text-center">
          <Amount label={t("recon.cardPurchases")} value={detail.transaction_total_minor} currency={currency} />
          <Amount label={t("recon.statementAmount")} value={detail.statement_total_minor} currency={currency} />
          <Amount label={t("recon.bankPayment")} value={bankAmount} currency={currency} />
        </div>
        <div className="mt-6 flex justify-center">
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-income-soft text-income font-semibold text-sm">
            {t("recon.reconciled")}
          </div>
        </div>
      </Card>
    );
  }

  if (detail.status === "pending") {
    const hasSuggestions = detail.bank_payment.status === "suggested";
    return (
      <Card className="p-6">
        <div className="grid grid-cols-3 gap-6 text-center">
          <Amount label={t("recon.cardPurchases")} value={detail.transaction_total_minor} currency={currency} />
          <Amount label={t("recon.statementAmount")} value={detail.statement_total_minor} currency={currency} />
          <div>
            <div className="text-xs font-medium text-ink-muted uppercase tracking-wide mb-1.5">{t("recon.bankPayment")}</div>
            <div className="text-lg font-semibold text-ink-faint">
              {hasSuggestions ? t("recon.needsConfirmation") : t("recon.notFound")}
            </div>
          </div>
        </div>
        <div className="mt-6 flex justify-center">
          <Badge tone="neutral">
            {hasSuggestions ? t("recon.pendingConfirm") : t("recon.pendingWaiting")}
          </Badge>
        </div>
      </Card>
    );
  }

  // mismatch
  return (
    <Card className="p-6 space-y-5">
      <DiffBlock
        title={t("recon.purchasesToStatement")}
        expectedLabel={t("recon.expectedFromPurchases")}
        expected={detail.transaction_total_minor}
        actualLabel={t("recon.statementAmount")}
        actual={detail.statement_total_minor}
        diff={detail.diff_transactions_vs_statement_minor}
        currency={currency}
      />
      {detail.bank_payment.status === "matched" && (
        <DiffBlock
          title={t("recon.statementToBank")}
          expectedLabel={t("recon.statementAmount")}
          expected={detail.statement_total_minor}
          actualLabel={t("recon.bankPayment")}
          actual={bankAmount}
          diff={detail.diff_statement_vs_bank_minor}
          currency={currency}
        />
      )}

      {detail.explanation_tags.length > 0 ? (
        <div className="flex flex-wrap gap-2 pt-1">
          {detail.explanation_tags.map((tag) => (
            <Badge key={tag} tone="warning">
              {explanationLabel(t, tag)}
            </Badge>
          ))}
        </div>
      ) : (
        <div className="text-sm text-ink-muted pt-1">
          {t("recon.unexplained")}
        </div>
      )}

      <div className="flex justify-center pt-1">
        <Badge tone="danger">{t("recon.needsReview")}</Badge>
      </div>
    </Card>
  );
}

function Amount({ label, value, currency }: { label: string; value: number | null; currency: string }) {
  return (
    <div>
      <div className="text-xs font-medium text-ink-muted uppercase tracking-wide mb-1.5">{label}</div>
      <div className="text-lg font-semibold tabular-nums text-ink">
        {value !== null ? formatMoney(value, currency) : "—"}
      </div>
    </div>
  );
}

function DiffBlock({
  title,
  expectedLabel,
  expected,
  actualLabel,
  actual,
  diff,
  currency,
}: {
  title: string;
  expectedLabel: string;
  expected: number | null;
  actualLabel: string;
  actual: number | null;
  diff: number | null;
  currency: string;
}) {
  const { t } = useI18n();
  const diffTone = diff === 0 ? "text-ink-muted" : diff !== null && diff > 0 ? "text-income" : "text-expense";
  return (
    <div className="rounded-md border border-border p-4">
      <div className="text-xs font-semibold text-ink uppercase tracking-wide mb-3">{title}</div>
      <div className="flex items-center justify-between text-sm py-1">
        <span className="text-ink-muted">{expectedLabel}</span>
        <span className="tabular-nums text-ink">{expected !== null ? formatMoney(expected, currency) : "—"}</span>
      </div>
      <div className="flex items-center justify-between text-sm py-1">
        <span className="text-ink-muted">{actualLabel}</span>
        <span className="tabular-nums text-ink">{actual !== null ? formatMoney(actual, currency) : "—"}</span>
      </div>
      <div className="flex items-center justify-between text-sm py-1 border-t border-border mt-1 pt-2 font-medium">
        <span className="text-ink">{t("recon.difference")}</span>
        <span className={`tabular-nums ${diffTone}`}>
          {diff !== null ? (diff > 0 ? `+${formatMoney(diff, currency)}` : formatMoney(diff, currency)) : "—"}
        </span>
      </div>
    </div>
  );
}
