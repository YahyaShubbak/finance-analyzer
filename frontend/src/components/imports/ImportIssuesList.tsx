import { useState } from "react";
import type { ImportIssue } from "../../types";
import { useI18n } from "../../i18n/useI18n";

const COLLAPSED_LIMIT = 4;

/** Errors and warnings from parsing. Warnings used to be hidden entirely,
 * so rows the parser couldn't read silently went missing. */
export function ImportIssuesList({ issues }: { issues: ImportIssue[] }) {
  const { t, tn } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const errors = issues.filter((i) => i.severity === "error");
  const warnings = issues.filter((i) => i.severity === "warning");
  const shownWarnings = expanded ? warnings : warnings.slice(0, COLLAPSED_LIMIT);

  if (issues.length === 0) return null;
  return (
    <div className="space-y-2">
      {errors.length > 0 && (
        <div className="rounded-md bg-danger-soft border border-danger/20 px-3 py-2 text-xs text-danger space-y-1">
          {errors.map((i, idx) => (
            <div key={idx}>{i.message}</div>
          ))}
        </div>
      )}
      {warnings.length > 0 && (
        <div className="rounded-md bg-warning-soft border border-warning/20 px-3 py-2 text-xs text-warning space-y-1">
          <div className="font-medium">
            {tn("issues.warnings", warnings.length)}
          </div>
          <ul className="list-disc pl-4 space-y-0.5">
            {shownWarnings.map((i, idx) => (
              <li key={idx}>{i.message}</li>
            ))}
          </ul>
          {warnings.length > COLLAPSED_LIMIT && (
            <button type="button" className="underline underline-offset-2" onClick={() => setExpanded((v) => !v)}>
              {expanded ? t("issues.showFewer") : t("issues.showAll", { count: warnings.length })}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
