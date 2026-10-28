import { useId, useState } from "react";
import { Badge, Button, Card } from "../ui";
import { RESOLUTION_TAG_OPTIONS, explanationLabel, resolutionTagKey } from "../../lib/explanationTags";
import { useI18n } from "../../i18n/useI18n";
import { useResolveReconciliation } from "../../hooks/useReconciliation";
import type { ReconciliationDetail } from "../../types";

export function ResolutionPanel({ detail }: { detail: ReconciliationDetail }) {
  const { t } = useI18n();
  const ids = useId();
  const [notes, setNotes] = useState(detail.resolution_notes ?? "");
  const [tags, setTags] = useState<string[]>(detail.user_resolution_tags);
  const resolve = useResolveReconciliation(detail.statement_id);

  function toggleTag(tag: string) {
    setTags((prev) => (prev.includes(tag) ? prev.filter((other) => other !== tag) : [...prev, tag]));
  }

  return (
    <Card>
      <div className="px-5 py-4 border-b border-border">
        <h2 className="text-sm font-semibold text-ink">{t("recon.resolution")}</h2>
      </div>

      <div className="px-5 py-4 border-b border-border">
        <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">{t("recon.computed")}</div>
        <div className="text-sm text-ink space-y-1">
          <div>
            {t("recon.statusLine")} <span className="font-medium">{t(`reconStatus.${detail.status}`)}</span>
          </div>
          <div>
            {t("recon.systemExplanations")}{" "}
            {detail.explanation_tags.length > 0 ? (
              detail.explanation_tags.map((tag) => (
                <Badge key={tag} tone="warning">
                  {explanationLabel(t, tag)}
                </Badge>
              ))
            ) : (
              <span className="text-ink-faint">{t("recon.noneDetected")}</span>
            )}
          </div>
        </div>
        <p className="text-xs text-ink-faint mt-2">
          {t("recon.computedHint")}
        </p>
      </div>

      <div className="px-5 py-4">
        <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">{t("recon.manual")}</div>

        {detail.resolved_by_user && (
          <div className="mb-3 text-xs text-income flex items-center gap-1.5">
            <span>✓</span> {t("recon.markedResolved")}
          </div>
        )}

        <label htmlFor={`${ids}-note`} className="text-xs text-ink-muted block mb-1">{t("recon.note")}</label>
        <textarea
          id={`${ids}-note`}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          placeholder={t("recon.notePlaceholder")}
          className="w-full text-sm border border-border-strong rounded-md px-3 py-2 bg-surface text-ink resize-none"
        />

        <div id={`${ids}-reason`} className="text-xs text-ink-muted mt-3 mb-1.5">{t("recon.reason")}</div>
        <div role="group" aria-labelledby={`${ids}-reason`} className="flex flex-wrap gap-1.5">
          {RESOLUTION_TAG_OPTIONS.map((opt) => (
            <button
              key={opt}
              type="button"
              aria-pressed={tags.includes(opt)}
              onClick={() => toggleTag(opt)}
              className={`text-xs px-2.5 py-1 rounded border transition-colors ${
                tags.includes(opt)
                  ? "bg-accent-soft border-accent text-accent-strong"
                  : "border-border-strong text-ink-muted hover:bg-surface-sunken"
              }`}
            >
              {t(resolutionTagKey(opt))}
            </button>
          ))}
        </div>

        <div className="mt-4">
          <Button
            variant="primary"
            disabled={resolve.isPending}
            onClick={() => resolve.mutate({ notes: notes || null, tags })}
          >
            {resolve.isPending ? t("common.saving") : t("recon.markResolved")}
          </Button>
        </div>
        {resolve.isError && <div className="mt-2 text-xs text-danger">{(resolve.error as Error).message}</div>}
      </div>
    </Card>
  );
}
