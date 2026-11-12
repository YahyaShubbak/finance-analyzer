import { useState } from "react";
import { useI18n } from "../i18n/useI18n";
import { PageHeader } from "../components/ui";
import { DropZone } from "../components/imports/DropZone";
import { ImportFileCard } from "../components/imports/ImportFileCard";
import { ImportHistory } from "../components/imports/ImportHistory";
import { loadAutoImportPreference, saveAutoImportPreference } from "../state/autoImportPreference";
import { addFiles, removeFile, saveSnapshot, useImportQueue } from "../state/importQueue";

export function Imports() {
  const { t } = useI18n();
  // kept outside the page: pending files survive a visit to another page
  const queue = useImportQueue();
  const [autoImport, setAutoImportState] = useState(loadAutoImportPreference);

  function setAutoImport(value: boolean) {
    setAutoImportState(value);
    saveAutoImportPreference(value);
  }

  return (
    <div>
      <PageHeader title={t("imports.title")} subtitle={t("imports.subtitle")} />
      <div className="p-8 space-y-6 max-w-4xl">
        <div className="space-y-2">
          <DropZone onFiles={addFiles} />
          <label className="flex items-start gap-2 text-xs text-ink-muted">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={autoImport}
              onChange={(e) => setAutoImport(e.target.checked)}
            />
            <span>{t("imports.autoImport")}</span>
          </label>
        </div>

        {queue.length > 0 && (
          <div className="space-y-3">
            {queue.map((qf) => (
              <ImportFileCard
                key={qf.key}
                file={qf.file}
                autoImport={autoImport}
                snapshot={qf.snapshot}
                onSnapshot={(patch) => saveSnapshot(qf.key, patch)}
                onRemove={() => removeFile(qf.key)}
              />
            ))}
          </div>
        )}

        <ImportHistory />
      </div>
    </div>
  );
}
