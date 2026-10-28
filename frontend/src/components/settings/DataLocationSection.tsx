import { Card } from "../ui";
import { useSystemInfo } from "../../hooks/useSystem";
import { useI18n } from "../../i18n/useI18n";

export function DataLocationSection() {
  const { t } = useI18n();
  const { data: info } = useSystemInfo();
  if (!info) return null;

  return (
    <Card>
      <div className="px-5 py-4 border-b border-border">
        <h2 className="text-sm font-semibold text-ink">{t("data.title")}</h2>
        <p className="text-xs text-ink-muted mt-1 max-w-lg">
          {t("data.body", { version: info.version })}
        </p>
      </div>
      {info.using_legacy_layout && (
        <div className="px-5 py-3 text-xs text-warning bg-warning-soft border-b border-warning/20">
          {t("data.legacy")}
        </div>
      )}
      <dl className="px-5 py-4 grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1.5 text-sm">
        <Entry label={t("data.database")} value={info.database_path} />
        <Entry label={t("data.imports")} value={info.imports_dir} />
        <Entry label={t("data.backups")} value={info.backups_dir} />
      </dl>
    </Card>
  );
}

function Entry({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-ink-muted">{label}</dt>
      <dd className="text-ink font-mono text-xs break-all self-center">{value}</dd>
    </>
  );
}
