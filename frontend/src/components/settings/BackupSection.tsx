import { Badge, Button, Card, ErrorState } from "../ui";
import { useBackups, useCreateBackup } from "../../hooks/useBackup";
import { backupDownloadUrl } from "../../api/backup";
import { formatBytes, formatDateTime } from "../../lib/format";
import { RestoreExistingButton } from "./RestoreExistingButton";
import { BreakableName } from "../ui/BreakableName";
import { useI18n } from "../../i18n/useI18n";

export function BackupSection() {
  const { t, tn } = useI18n();
  const { data: backups, isLoading, isError, error, refetch } = useBackups();
  const create = useCreateBackup();

  return (
    <Card>
      <div className="px-5 py-4 border-b border-border flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">{t("backup.title")}</h2>
          <p className="text-xs text-ink-muted mt-1 max-w-lg">
            {t("backup.body")}
          </p>
        </div>
        <Button variant="primary" onClick={() => create.mutate()} disabled={create.isPending}>
          {create.isPending ? t("backup.creating") : t("backup.create")}
        </Button>
      </div>

      {create.isError && (
        <div className="px-5 py-3 text-xs text-danger bg-danger-soft border-b border-danger/20">
          {(create.error as Error).message}
        </div>
      )}

      {/* not an empty list: the backups could not be loaded */}
      {isError && !backups && <ErrorState error={error} onRetry={() => refetch()} />}
      {!isLoading && backups && backups.length === 0 && (
        <div className="px-5 py-6 text-sm text-ink-muted">{t("backup.none")}</div>
      )}

      {backups && backups.length > 0 && (
        <div className="overflow-x-auto">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-ink-muted text-xs">
                <tr className="border-b border-border">
                  <th className="text-left font-medium px-5 py-2">{t("backup.col.backup")}</th>
                  <th className="text-left font-medium px-5 py-2">{t("backup.col.created")}</th>
                  <th className="text-left font-medium px-5 py-2">{t("backup.col.contains")}</th>
                  <th className="text-right font-medium px-5 py-2">{t("backup.col.size")}</th>
                  <th className="px-5 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {backups.map((b) => (
                  <tr key={b.filename} className="border-b border-border last:border-0">
                    <td className="px-5 py-2.5 text-ink min-w-[10rem] [overflow-wrap:anywhere]">
                      <BreakableName name={b.filename} />
                    </td>
                    <td className="px-5 py-2.5 text-ink-muted whitespace-nowrap">{formatDateTime(b.created_at)}</td>
                    <td className="px-5 py-2.5">
                      <div className="flex flex-wrap gap-1">
                        <Badge tone="neutral">{tn("backup.accounts", b.counts.accounts ?? 0)}</Badge>
                        <Badge tone="neutral">{tn("backup.transactions", b.counts.transactions ?? 0)}</Badge>
                        <Badge tone="neutral">{tn("backup.imports", b.counts.imports ?? 0)}</Badge>
                      </div>
                    </td>
                    <td className="px-5 py-2.5 text-right tabular-nums text-ink-muted">{formatBytes(b.size_bytes)}</td>
                    <td className="px-5 py-2.5">
                      <div className="flex justify-end gap-2">
                        <a
                          href={backupDownloadUrl(b.filename)}
                          className="text-xs text-accent-strong underline underline-offset-2 self-center"
                        >
                          {t("backup.download")}
                        </a>
                        <RestoreExistingButton filename={b.filename} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}
