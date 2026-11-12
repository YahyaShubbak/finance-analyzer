import { useState } from "react";
import { useI18n } from "../i18n/useI18n";
import { PageHeader } from "../components/ui";
import { DropZone } from "../components/imports/DropZone";
import { ImportFileCards } from "../components/imports/ImportFileCards";
import { ImportHistory } from "../components/imports/ImportHistory";
import { loadAutoImportPreference, saveAutoImportPreference } from "../state/autoImportPreference";
import { addFiles } from "../state/importQueue";

export function Imports() {
  const { t } = useI18n();
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

        <ImportFileCards autoImport={autoImport} />

        <ImportHistory />
      </div>
    </div>
  );
}
