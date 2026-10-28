import { Button } from "../ui";
import { categoryLabel } from "../../lib/categories";
import { useI18n } from "../../i18n/useI18n";
import type { useCategoryAssignment } from "../../hooks/useCategoryAssignment";

/** The "learn for similar transactions" choice and the outcome of the last
 * assignment, shown above a list whose categories can be changed. */
export function CategoryAssignmentBar({
  learn,
  setLearn,
  notice,
  dismiss,
  forget,
  forgetting,
  error,
}: ReturnType<typeof useCategoryAssignment>) {
  const { t, tn } = useI18n();
  return (
    <div className="px-5 py-2.5 border-b border-border space-y-2">
      <label className="flex items-center gap-2 text-xs text-ink-muted">
        <input type="checkbox" checked={learn} onChange={(e) => setLearn(e.target.checked)} />
        {t("tx.learn")}
      </label>
      <div role="status" aria-live="polite">
        {notice && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-accent-soft px-3 py-2 text-xs text-accent-strong">
            <span className="flex-1 min-w-[240px]">
              {notice.kind === "learned" &&
                (notice.applied > 0
                  ? tn("tx.learned", notice.applied, {
                      pattern: notice.pattern,
                      category: categoryLabel(t, notice.category),
                    })
                  : t("tx.learnedNone", { pattern: notice.pattern, category: categoryLabel(t, notice.category) }))}
              {notice.kind === "notLearnable" && t("tx.notLearnable", { category: categoryLabel(t, notice.category) })}
              {notice.kind === "only" && t("tx.changedOnly", { category: categoryLabel(t, notice.category) })}
              {notice.kind === "forgotten" && tn("tx.forgotten", notice.count)}
            </span>
            {notice.kind === "learned" && (
              <Button
                variant="secondary"
                className="!px-2.5 !py-1 text-xs"
                disabled={forgetting}
                onClick={() => forget(notice.ruleId)}
              >
                {forgetting ? t("tx.forgetting") : t("tx.forget")}
              </Button>
            )}
            <button type="button" className="underline underline-offset-2" onClick={dismiss}>
              {t("tx.dismiss")}
            </button>
          </div>
        )}
        {error && <div className="text-xs text-danger">{error.message}</div>}
      </div>
    </div>
  );
}
