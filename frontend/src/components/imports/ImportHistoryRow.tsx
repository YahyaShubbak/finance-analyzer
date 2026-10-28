import { useState } from "react";
import { useI18n } from "../../i18n/useI18n";
import { Button } from "../ui";
import { BreakableName } from "../ui/BreakableName";
import { formatDateTime } from "../../lib/format";
import { useRemoveImport } from "../../hooks/useImports";
import type { ImportRecord } from "../../types";

export function ImportHistoryRow({
  record,
  selected,
  onToggle,
}: {
  record: ImportRecord;
  selected: boolean;
  onToggle: () => void;
}) {
  const { t } = useI18n();
  const [confirming, setConfirming] = useState(false);
  const remove = useRemoveImport();

  return (
    <>
      <tr className={`border-b border-border last:border-0 ${selected ? "bg-accent-soft/40" : ""}`}>
        <td className="px-5 py-2.5 text-ink min-w-[10rem] [overflow-wrap:anywhere]">
          <BreakableName name={record.filename} />
        </td>
        <td className="px-5 py-2.5 text-ink-muted">{record.account_name}</td>
        <td className="px-5 py-2.5 text-ink-muted">
          {record.document_type === "credit_card_statement" ? t("imports.docType.card") : t("imports.docType.bank")}
        </td>
        <td className="px-5 py-2.5 text-ink-muted whitespace-nowrap">{formatDateTime(record.imported_at)}</td>
        <td className="px-5 py-2.5 text-right tabular-nums text-ink">{record.detected_transaction_count}</td>
        <td className="px-5 py-2.5 text-right whitespace-nowrap">
          <div className="inline-flex items-center gap-2">
            {!confirming && (
              <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => setConfirming(true)}>
                {t("common.remove")}
              </Button>
            )}
            <input
              type="checkbox"
              checked={selected}
              onChange={onToggle}
              aria-label={t("imports.selectRow", { file: record.filename })}
            />
          </div>
        </td>
      </tr>
      {confirming && (
        <tr className="border-b border-border last:border-0 bg-danger-soft/40">
          <td colSpan={6} className="px-5 py-3">
            <p className="text-sm text-ink">{t("imports.removeConfirm", { file: record.filename })}</p>
            {remove.isError && (
              <p className="text-xs text-danger mt-2">{(remove.error as Error).message}</p>
            )}
            <div className="mt-3 flex gap-2">
              <Button
                variant="primary"
                className="!bg-danger hover:!bg-danger"
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate(record.id, {
                    onSuccess: () => setConfirming(false),
                  })
                }
              >
                {remove.isPending ? t("imports.removing") : t("imports.removeYes")}
              </Button>
              <Button variant="ghost" onClick={() => setConfirming(false)} disabled={remove.isPending}>
                {t("common.cancel")}
              </Button>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
