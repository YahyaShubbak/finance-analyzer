import { useState } from "react";
import { Button } from "../ui";
import { useRestoreFromExisting } from "../../hooks/useBackup";
import { useI18n } from "../../i18n/useI18n";

export function RestoreExistingButton({ filename }: { filename: string }) {
  const { t } = useI18n();
  const [confirming, setConfirming] = useState(false);
  const restore = useRestoreFromExisting();
  const [result, setResult] = useState<{ safety_backup: string } | null>(null);

  if (result) {
    return (
      <span className="text-xs text-income">
        {t("restore.restored", { file: result.safety_backup })}
      </span>
    );
  }

  if (!confirming) {
    return (
      <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => setConfirming(true)}>
        {t("restore.restore")}
      </Button>
    );
  }

  return (
    <div className="text-left bg-danger-soft border border-danger/30 rounded-md p-3 text-xs max-w-xs">
      <p className="text-ink mb-2">
        <span className="font-semibold">{t("restore.replaceAll")}</span> {t("restore.confirmExisting", { file: filename })}
      </p>
      {restore.isError && <p className="text-danger mb-2">{(restore.error as Error).message}</p>}
      <div className="flex gap-2">
        <Button
          variant="primary"
          className="!bg-danger hover:!bg-danger !px-2 !py-1 text-xs"
          disabled={restore.isPending}
          onClick={() =>
            restore.mutate(filename, {
              onSuccess: (data) => setResult({ safety_backup: data.safety_backup }),
            })
          }
        >
          {restore.isPending ? t("restore.restoring") : t("restore.yes")}
        </Button>
        <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => setConfirming(false)} disabled={restore.isPending}>
          {t("common.cancel")}
        </Button>
      </div>
    </div>
  );
}
