import { useId, useState } from "react";
import clsx from "clsx";
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, Pager } from "../components/ui";
import { useAssignCategory, useReviewGroups } from "../hooks/useTransactions";
import { useCategoryNames } from "../hooks/useCategories";
import { TransactionCorrectionForm } from "../components/review/TransactionCorrectionForm";
import { categoryLabel } from "../lib/categories";
import { formatDate, formatSignedMoney } from "../lib/format";
import { loadLearnPreference, saveLearnPreference } from "../state/learnPreference";
import { useI18n } from "../i18n/useI18n";
import type { ReviewGroup } from "../types";

/** Members shown before "show all" in a group. */
const SHOWN = 5;

/**
 * The review queue, grouped by payee — the groups a learned category would
 * cover together, biggest first: one category for a whole group at once,
 * its members side by side to see that they really belong together (and
 * to leave out the ones that don't).
 */
export function ReviewQueue() {
  const { t, tn } = useI18n();
  const [page, setPage] = useState(1);
  const { data, isLoading, isError, error, refetch } = useReviewGroups(page);
  // What an assignment did: shown here, because the group leaves the queue at once.
  const [notice, setNotice] = useState<string | null>(null);
  const pages = Math.max(1, Math.ceil((data?.total_groups ?? 0) / (data?.page_size ?? 20)));
  if (data && page > pages) setPage(pages);

  return (
    <div>
      <PageHeader title={t("review.title")} subtitle={t("review.subtitle")} />
      <div className="p-8 max-w-4xl space-y-4">
        {notice && (
          <div role="status" className="flex items-start gap-3 rounded-md bg-accent-soft px-3 py-2 text-xs text-accent-strong">
            <span className="flex-1">{notice}</span>
            <button type="button" className="underline underline-offset-2" onClick={() => setNotice(null)}>
              {t("tx.dismiss")}
            </button>
          </div>
        )}

        {isError && (
          <Card>
            <ErrorState error={error} onRetry={() => refetch()} />
          </Card>
        )}

        {!isLoading && data && data.total_transactions === 0 && (
          <Card>
            <EmptyState title={t("review.emptyTitle")} description={t("review.emptyBody")} />
          </Card>
        )}

        {data && data.total_transactions > 0 && (
          <>
            <p className="text-sm text-ink-muted">
              {tn("review.groupsSummary", data.total_transactions, { groups: data.total_groups })}
            </p>
            {data.groups.map((group) => (
              <ReviewGroupCard key={group.key} group={group} onNotice={setNotice} />
            ))}
            {pages > 1 && (
              <div className="flex justify-end">
                <Pager page={page} pages={pages} onChange={setPage} />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function ReviewGroupCard({ group, onNotice }: { group: ReviewGroup; onNotice: (text: string) => void }) {
  const { t, tn } = useI18n();
  const ids = useId();
  const categories = useCategoryNames();
  const assign = useAssignCategory();
  const [category, setCategory] = useState(group.suggested_category ?? "");
  const [learn, setLearnState] = useState(loadLearnPreference);
  const [excluded, setExcluded] = useState<Set<number>>(new Set());
  const [showAll, setShowAll] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  // After a refetch the group may have lost members; only current ones count as left out.
  // (a big group lists only its newest bookings; member_ids has them all)
  const leftOut = group.member_ids.filter((id) => excluded.has(id));
  const chosen = group.member_ids.filter((id) => !excluded.has(id));
  const shown = showAll ? group.transactions : group.transactions.slice(0, SHOWN);

  function setLearn(value: boolean) {
    setLearnState(value);
    saveLearnPreference(value);
  }

  function toggle(id: number) {
    const next = new Set(excluded);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setExcluded(next);
  }

  async function submit() {
    if (!category || chosen.length === 0) return;
    const withRule = learn && group.learnable;
    try {
      const result = await assign.mutateAsync({
        ids: chosen,
        category,
        learn: withRule,
        leaveOut: leftOut,
      });
      const name = categoryLabel(t, category);
      let text = tn("review.assigned", result.updated, { category: name });
      if (result.rule) {
        text += " " + t("review.assignedRule", { pattern: result.rule.pattern });
        if (result.applied_to > 0) text += " " + tn("review.assignedMore", result.applied_to);
      }
      onNotice(text);
    } catch {
      // shown below the button
    }
  }

  return (
    <Card>
      <div className="px-5 py-4 border-b border-border space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-ink truncate">{group.label}</h2>
            <div className="text-xs text-ink-muted mt-0.5">
              {tn("review.groupCount", group.count)} · {formatSignedMoney(group.total_minor, group.currency)}
            </div>
          </div>
          {group.count > 1 && <Badge tone="warning">{tn("review.groupBadge", group.count)}</Badge>}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor={`${ids}-cat`} className="text-xs text-ink-muted">
            {t("review.categoryFor")}
          </label>
          <select
            id={`${ids}-cat`}
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink"
          >
            <option value="">{t("review.chooseCategory")}</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {categoryLabel(t, c)}
                {c === group.suggested_category ? ` (${t("review.suggested")})` : ""}
              </option>
            ))}
          </select>
          <Button variant="primary" className="!py-1.5 text-xs" disabled={!category || chosen.length === 0 || assign.isPending} onClick={submit}>
            {assign.isPending
              ? t("common.saving")
              : chosen.length === 1
                ? t("review.assignOne")
                : tn("review.assignAll", chosen.length)}
          </Button>
          {group.learnable && (
            <label className="flex items-center gap-1.5 text-xs text-ink-muted">
              <input type="checkbox" checked={learn} onChange={(e) => setLearn(e.target.checked)} />
              {t("review.learnGroup")}
            </label>
          )}
        </div>
        {assign.error && <p className="text-xs text-danger">{(assign.error as Error).message}</p>}
      </div>

      <ul className="divide-y divide-border">
        {shown.map((tx) => {
          const open = expandedId === tx.id;
          const out = excluded.has(tx.id);
          return (
            <li key={tx.id} className="px-5 py-2.5">
              <div className="flex items-center gap-3">
                {(group.member_ids.length > 1 || out) && (
                  <input
                    type="checkbox"
                    checked={!out}
                    onChange={() => toggle(tx.id)}
                    aria-label={t("review.includeTx", { text: tx.normalized_description })}
                  />
                )}
                <button
                  type="button"
                  aria-expanded={open}
                  onClick={() => setExpandedId(open ? null : tx.id)}
                  className={clsx(
                    "flex-1 min-w-0 flex items-center justify-between gap-3 text-left rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent",
                    out && "opacity-50"
                  )}
                >
                  <span className="min-w-0">
                    <span className="block text-sm text-ink truncate" title={tx.normalized_description}>
                      {tx.normalized_description}
                    </span>
                    <span className="block text-xs text-ink-faint">
                      {formatDate(tx.transaction_date)} · {tx.account_name}
                      {tx.category ? ` · ${categoryLabel(t, tx.category)}` : ""}
                    </span>
                  </span>
                  <span className="flex items-center gap-2 shrink-0">
                    <span className={clsx("text-sm tabular-nums", tx.amount_minor > 0 ? "text-income" : tx.amount_minor < 0 ? "text-expense" : "text-ink-muted")}>
                      {formatSignedMoney(tx.amount_minor, tx.currency)}
                    </span>
                    <span aria-hidden className="text-ink-faint text-xs">{open ? "▲" : "▼"}</span>
                  </span>
                </button>
              </div>
              {open && (
                <div className="mt-3 pt-3 border-t border-border">
                  <TransactionCorrectionForm
                    transaction={tx}
                    onResolved={() => setExpandedId(null)}
                    onNotice={(text) => {
                      onNotice(text);
                      setExpandedId(null);
                    }}
                  />
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {group.count > SHOWN && (
        <div className="px-5 py-2 border-t border-border">
          <button type="button" className="text-xs text-accent-strong underline underline-offset-2" onClick={() => setShowAll(!showAll)}>
            {showAll ? t("review.showFewer") : tn("review.showAll", group.transactions.length)}
          </button>
          {showAll && group.count > group.transactions.length && (
            <span className="ml-3 text-xs text-ink-faint">
              {tn("review.moreNotListed", group.count - group.transactions.length)}
            </span>
          )}
        </div>
      )}
    </Card>
  );
}
