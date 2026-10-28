import { useRef, useState } from "react";
import { Button, Card } from "../ui";
import { useRestoreFromUpload } from "../../hooks/useBackup";
import { useI18n } from "../../i18n/useI18n";

export function RestoreFromFileSection() {
  const { t } = useI18n();
  const [file, setFile] = useState<File | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<{ safety_backup: string } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const restore = useRestoreFromUpload();

  return (
    <Card className="p-5">
      <h2 className="text-sm font-semibold text-ink">{t("restore.fileTitle")}</h2>
      <p className="text-xs text-ink-muted mt-1 max-w-lg">
        {t("restore.fileBody")}
      </p>

      <div className="mt-3 flex items-center gap-2">
        <input
          ref={inputRef}
          type="file"
          accept=".zip"
          aria-label={t("restore.chooseFile")}
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setConfirming(false);
            setResult(null);
          }}
          className="text-sm text-ink-muted"
        />
        {file && !confirming && !result && (
          <Button variant="secondary" className="!px-2.5 !py-1.5 text-xs" onClick={() => setConfirming(true)}>
            {t("restore.thisFile")}
          </Button>
        )}
      </div>

      {confirming && file && (
        <div className="mt-3 bg-danger-soft border border-danger/30 rounded-md p-3 text-sm max-w-lg">
          <p className="text-ink mb-2">
            <span className="font-semibold">{t("restore.replaceAll")}</span> {t("restore.confirmFile", { file: file.name })}
          </p>
          {restore.isError && <p className="text-xs text-danger mb-2">{(restore.error as Error).message}</p>}
          <div className="flex gap-2">
            <Button
              variant="primary"
              className="!bg-danger hover:!bg-danger"
              disabled={restore.isPending}
              onClick={() =>
                restore.mutate(file, {
                  onSuccess: (data) => {
                    setResult({ safety_backup: data.safety_backup });
                    setConfirming(false);
                  },
                })
              }
            >
              {restore.isPending ? t("restore.restoring") : t("restore.yes")}
            </Button>
            <Button variant="ghost" onClick={() => setConfirming(false)} disabled={restore.isPending}>
              {t("common.cancel")}
            </Button>
          </div>
        </div>
      )}

      {result && (
        <div className="mt-3 text-xs text-income">
          {t("restore.complete", { file: result.safety_backup })}
        </div>
      )}
    </Card>
  );
}
