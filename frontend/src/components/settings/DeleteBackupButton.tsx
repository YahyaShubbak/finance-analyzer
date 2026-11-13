import { useState } from "react";
import { Button } from "../ui";
import { useDeleteBackup } from "../../hooks/useBackup";
import { useI18n } from "../../i18n/useI18n";

/** Removes one backup from this machine — asked about first: it can't be brought back. */
export function DeleteBackupButton({ filename }: { filename: string }) {
  const { t } = useI18n();
  const [confirming, setConfirming] = useState(false);
  const remove = useDeleteBackup();

  if (!confirming) {
    return (
      <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => setConfirming(true)}>
        {t("backup.delete")}
      </Button>
    );
  }

  return (
    <div className="text-left bg-danger-soft border border-danger/30 rounded-md p-3 text-xs max-w-xs">
      <p className="text-ink mb-2">{t("backup.deleteConfirm", { file: filename })}</p>
      {remove.isError && <p className="text-danger mb-2">{(remove.error as Error).message}</p>}
      <div className="flex gap-2">
        <Button
          variant="primary"
          className="!bg-danger hover:!bg-danger !px-2 !py-1 text-xs"
          disabled={remove.isPending}
          onClick={() => remove.mutate(filename)}
        >
          {t("backup.deleteYes")}
        </Button>
        <Button
          variant="ghost"
          className="!px-2 !py-1 text-xs"
          disabled={remove.isPending}
          onClick={() => {
            remove.reset();
            setConfirming(false);
          }}
        >
          {t("common.cancel")}
        </Button>
      </div>
    </div>
  );
}
