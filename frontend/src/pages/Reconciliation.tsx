import { useParams } from "react-router-dom";
import { Card, EmptyState, ErrorState, PageHeader } from "../components/ui";
import { ReconciliationSummary } from "../components/reconciliation/ReconciliationSummary";
import { StatementTransactionsTable } from "../components/reconciliation/StatementTransactionsTable";
import { BankPaymentPanel } from "../components/reconciliation/BankPaymentPanel";
import { ResolutionPanel } from "../components/reconciliation/ResolutionPanel";
import { useReconciliationDetail } from "../hooks/useReconciliation";
import { formatDate } from "../lib/format";
import { useI18n } from "../i18n/useI18n";

export function Reconciliation() {
  const { t } = useI18n();
  const { statementId } = useParams<{ statementId: string }>();
  const id = statementId ? Number(statementId) : undefined;
  const { data: detail, isLoading, isError, error, refetch } = useReconciliationDetail(id);

  if (!id) {
    return (
      <div>
        <PageHeader title={t("recon.title")} subtitle={t("recon.subtitle")} />
        <div className="p-8">
          <Card>
            <EmptyState
              title={t("recon.selectTitle")}
              description={t("recon.selectBody")}
            />
          </Card>
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div>
        <PageHeader title={t("recon.title")} />
        <div className="p-8">
          <Card>
            <ErrorState error={error} onRetry={() => refetch()} />
          </Card>
        </div>
      </div>
    );
  }

  if (isLoading || !detail) {
    return (
      <div>
        <PageHeader title={t("recon.title")} />
        <div className="p-8 text-sm text-ink-muted">{t("common.loading")}</div>
      </div>
    );
  }

  const period =
    detail.statement_period_start && detail.statement_period_end
      ? `${formatDate(detail.statement_period_start)} – ${formatDate(detail.statement_period_end)}`
      : t("recon.unknownPeriod");

  return (
    <div>
      <PageHeader
        title={t("recon.statementOf", { account: detail.account_name })}
        subtitle={t("recon.importedFrom", { period, file: detail.source_import_filename ?? t("recon.unknownSource") })}
      />
      <div className="p-8 space-y-6 max-w-4xl">
        <ReconciliationSummary detail={detail} />
        <BankPaymentPanel detail={detail} />
        <StatementTransactionsTable transactions={detail.transactions} />
        <ResolutionPanel detail={detail} />
      </div>
    </div>
  );
}
