import { useId, useState } from "react";
import { Button, Card } from "../ui";
import { useResetEverything } from "../../hooks/useSystem";
import { useCreateBackup } from "../../hooks/useBackup";
import { clearQueue } from "../../state/importQueue";
import { useI18n } from "../../i18n/useI18n";

// what this browser remembers besides the language
const STORED_PREFERENCES = ["finance.filters.v1", "finance.autoImport", "finance.learnCategories"];

/** Start over: everything is deleted (backups only when asked). Typed
 * confirmation, and a backup offered first — this can't be undone. */
export function ResetSection() {
  const { t } = useI18n();
  const ids = useId();
  const reset = useResetEverything();
  const backup = useCreateBackup();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [withBackups, setWithBackups] = useState(false);
  const word = t("reset.word");
  const confirmed = typed.trim().toUpperCase() === word.toUpperCase();

  async function run() {
    try {
      await reset.mutateAsync(withBackups);
    } catch {
      return; // shown below
    }
    clearQueue();
    for (const key of STORED_PREFERENCES) {
      try {
        localStorage.removeItem(key);
      } catch {
        // storage blocked: nothing stored either
      }
    }
    setOpen(false);
    setTyped("");
  }

  return (
    <Card className="border-danger/40">
      <div className="px-5 py-4 flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-xl">
          <h2 className="text-sm font-semibold text-danger">{t("reset.title")}</h2>
          <p className="text-xs text-ink-muted mt-1">{t("reset.body")}</p>
        </div>
        {!open && (
          <Button variant="danger" onClick={() => setOpen(true)}>
            {t("reset.start")}
          </Button>
        )}
      </div>

      {reset.isSuccess && !open && (
        <div role="status" className="px-5 py-3 border-t border-border text-xs text-income">
          {t("reset.done")}
        </div>
      )}

      {open && (
        <div className="px-5 py-4 border-t border-danger/30 bg-danger-soft/40 space-y-3 text-sm">
          <p className="text-ink">{t("reset.warning")}</p>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <Button variant="secondary" className="!py-1 text-xs" disabled={backup.isPending} onClick={() => backup.mutate()}>
              {backup.isPending ? t("backup.creating") : t("reset.backupFirst")}
            </Button>
            {backup.isSuccess && <span className="text-income">{t("reset.backupMade")}</span>}
            {backup.isError && <span className="text-danger">{(backup.error as Error).message}</span>}
          </div>
          <label className="flex items-center gap-2 text-xs text-ink">
            <input type="checkbox" checked={withBackups} onChange={(e) => setWithBackups(e.target.checked)} />
            {t("reset.withBackups")}
          </label>
          <div>
            <label htmlFor={`${ids}-word`} className="block text-xs text-ink-muted mb-1">
              {t("reset.typeToConfirm", { word })}
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <input
                id={`${ids}-word`}
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                autoComplete="off"
                className="w-40 rounded-md border border-border-strong bg-surface px-2.5 py-1.5 text-sm text-ink"
              />
              <Button variant="danger" disabled={!confirmed || reset.isPending} onClick={run}>
                {reset.isPending ? t("reset.running") : t("reset.confirm")}
              </Button>
              <Button
                variant="ghost"
                onClick={() => {
                  setOpen(false);
                  setTyped("");
                }}
              >
                {t("common.cancel")}
              </Button>
            </div>
          </div>
          {reset.isError && <p className="text-xs text-danger">{(reset.error as Error).message}</p>}
        </div>
      )}
    </Card>
  );
}
