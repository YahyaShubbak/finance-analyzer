import { useState } from "react";
import { Button, Card } from "../ui";
import { useRerunTransferDetection } from "../../hooks/useTransfers";
import type { TransferDetectionResult } from "../../types";
import type { I18n } from "../../i18n/core";
import { useI18n } from "../../i18n/useI18n";

export function RecheckTransfersCard() {
  const { t, tn } = useI18n();
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<TransferDetectionResult | null>(null);
  const rerun = useRerunTransferDetection();

  function handleConfirm() {
    rerun.mutate(undefined, {
      onSuccess: (data) => {
        setResult(data);
        setConfirming(false);
      },
    });
  }

  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">{t("transfers.title")}</h2>
          <p className="text-xs text-ink-muted mt-1 max-w-md">{t("transfers.body")}</p>
        </div>
        {!confirming && (
          <Button variant="secondary" onClick={() => { setConfirming(true); setResult(null); }} disabled={rerun.isPending}>
            {t("transfers.recheck")}
          </Button>
        )}
      </div>

      {confirming && (
        <div className="mt-4 rounded-md border border-border-strong bg-surface-sunken px-4 py-3">
          <p className="text-sm text-ink">{t("transfers.confirm")}</p>
          <div className="mt-3 flex gap-2">
            <Button variant="primary" onClick={handleConfirm} disabled={rerun.isPending}>
              {rerun.isPending ? t("transfers.checking") : t("transfers.confirmYes")}
            </Button>
            <Button variant="ghost" onClick={() => setConfirming(false)} disabled={rerun.isPending}>
              {t("common.cancel")}
            </Button>
          </div>
        </div>
      )}

      {rerun.isError && (
        <div className="mt-4 rounded-md bg-danger-soft border border-danger/20 px-4 py-3 text-sm text-danger">
          {t("transfers.error", { message: (rerun.error as Error).message })}
        </div>
      )}

      {result && !rerun.isError && (
        <div className="mt-4 rounded-md bg-income-soft border border-income/20 px-4 py-3 text-sm text-income">
          {describeResult(result, t, tn)}
        </div>
      )}
    </Card>
  );
}

function describeResult(result: TransferDetectionResult, t: I18n["t"], tn: I18n["tn"]): string {
  const { transactions_considered, pairs_matched, transactions_reverted_to_ordinary } = result;

  if (transactions_considered === 0) return t("transfers.none");
  if (pairs_matched === 0 && transactions_reverted_to_ordinary === 0) {
    return tn("transfers.noneFound", transactions_considered);
  }
  let text = t("transfers.found", { count: transactions_considered, pairs: pairs_matched });
  if (transactions_reverted_to_ordinary > 0) {
    text += tn("transfers.reverted", transactions_reverted_to_ordinary);
  }
  return `${text}.`;
}
