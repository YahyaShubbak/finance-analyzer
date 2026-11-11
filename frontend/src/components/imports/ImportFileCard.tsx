import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Button, Card } from "../ui";
import { ImportSummaryCounts } from "./ImportSummaryCounts";
import { DuplicateRowCard } from "./DuplicateRowCard";
import { ColumnMappingForm } from "./ColumnMappingForm";
import { ImportIssuesList } from "./ImportIssuesList";
import { ImportReview } from "./ImportReview";
import {
  useCommitImport,
  useDiscardStagedImport,
  useImportHistory,
  usePreviewImport,
  useRecognizeImport,
  useRemoveImport,
  useReparseImport,
} from "../../hooks/useImports";
import { useAccounts } from "../../hooks/useAccounts";
import { useI18n } from "../../i18n/useI18n";
import { formatDate, formatMoney, formatSignedMoney } from "../../lib/format";
import { isSameImport, noteLearned, useLearnedVersion, type CardSnapshot } from "../../state/importQueue";
import type {
  Account,
  ImportCommitResult,
  ImportPreview,
  ParseOptions,
  PdfTemplate,
  ParsedTransactionPreview,
  RowDecisionValue,
} from "../../types";

function defaultDecisionFor(status: string): RowDecisionValue {
  return status === "exact_duplicate" ? "skip" : "keep";
}

function initialDecisions(preview: ImportPreview): Record<number, RowDecisionValue> {
  const initial: Record<number, RowDecisionValue> = {};
  for (const row of preview.row_classifications) {
    if (row.status !== "new") initial[row.source_row_index] = defaultDecisionFor(row.status);
  }
  return initial;
}

export function ImportFileCard({
  file,
  autoImport,
  snapshot,
  onSnapshot,
  onDone,
  onRemove,
}: {
  file: File;
  /** import right away when the account is recognized and the preview shows nothing to check */
  autoImport: boolean;
  /** where the card was before the page was left (see state/importQueue) */
  snapshot: CardSnapshot;
  onSnapshot: (patch: CardSnapshot) => void;
  onDone: () => void;
  onRemove: () => void;
}) {
  const { t, tn } = useI18n();
  const { data: accounts } = useAccounts();

  const [p, setPreview] = useState<ImportPreview | undefined>(snapshot.preview);
  const [committed, setCommitted] = useState<ImportCommitResult | undefined>(snapshot.committed);
  const [seenInHistory, setSeenInHistory] = useState(Boolean(snapshot.seenInHistory));
  const [showDetails, setShowDetails] = useState(false);
  const [showRows, setShowRows] = useState(false);
  const [showMapping, setShowMapping] = useState(false);
  const [warningsConfirmed, setWarningsConfirmed] = useState(false);
  const [decisions, setDecisions] = useState<Record<number, RowDecisionValue>>(
    snapshot.preview ? initialDecisions(snapshot.preview) : {}
  );
  // The user took over: chose or changed the account, or undid an import.
  // Nothing is then imported without their click.
  const [manual, setManual] = useState(Boolean(snapshot.manual));
  const [pickAccount, setPickAccount] = useState(false);
  const [undone, setUndone] = useState(Boolean(snapshot.undone));
  const [formOptions, setFormOptions] = useState(Boolean(snapshot.formOptions));
  const [autoRefused, setAutoRefused] = useState<string | null>(null);
  const [autoImported, setAutoImported] = useState(Boolean(snapshot.autoImported));
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewDismissed, setReviewDismissed] = useState(Boolean(snapshot.reviewDismissed));

  const preview = usePreviewImport();
  const reparse = useReparseImport();
  const recognize = useRecognizeImport();
  const discard = useDiscardStagedImport();
  const commit = useCommitImport();
  const removal = useRemoveImport();
  const history = useImportHistory();
  const started = useRef(false);

  // keep the card's progress when the page is left
  useEffect(() => {
    onSnapshot({ preview: p, committed, seenInHistory, autoImported, manual, undone, formOptions, reviewDismissed });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p, committed, seenInHistory, autoImported, manual, undone, formOptions, reviewDismissed]);

  function applyPreview(data: ImportPreview) {
    setPreview(data);
    setDecisions(initialDecisions(data));
    setWarningsConfirmed(false);
    setShowMapping(data.ambiguous && data.available_columns.length > 0);
  }

  // Read the file right away; the backend recognizes its account if it can.
  useEffect(() => {
    if (started.current || snapshot.preview || snapshot.committed || snapshot.undone) return;
    started.current = true;
    preview.mutate({ file }, { onSuccess: applyPreview });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const accountId = p?.account_id ?? undefined;
  // A file nothing could be read from: no point asking for its account.
  const unreadable = p !== undefined && p.has_errors && p.transaction_count === 0;

  function reparseWith(options: ParseOptions, targetAccountId = accountId) {
    if (!p || !targetAccountId) return;
    reparse.mutate({ stagingId: p.staging_id, accountId: targetAccountId, options }, { onSuccess: applyPreview });
  }

  // The user taught the reader in the review: read the file again with it
  // (also before an account is chosen).
  function teach(template: PdfTemplate | null) {
    if (!p) return;
    reparse.mutate(
      { stagingId: p.staging_id, accountId: p.account_id, options: { ...p.options, pdf_template: template } },
      { onSuccess: applyPreview }
    );
  }

  // For another account the app decides anew about inverting the amounts —
  // unless the user chose it in the column/format dialog.
  function optionsForAnotherAccount(options: ParseOptions): ParseOptions {
    return formOptions ? options : { ...options, invert_signs: null };
  }

  // Not recognized, but there is only one account: that one (confirmed by the user's click).
  const onlyAccount = accounts?.length === 1 ? accounts[0].id : undefined;
  useEffect(() => {
    if (p && p.account_id === null && !unreadable && onlyAccount !== undefined && !reparse.isPending && !manual) {
      setManual(true);
      reparseWith(optionsForAnotherAccount(p.options), onlyAccount);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p, onlyAccount]);

  function changeAccount(id: number) {
    accountChosen.current = true;
    setManual(true);
    setPickAccount(false);
    if (p && !committed) {
      // Duplicate detection depends on the account: re-classify the already
      // uploaded file instead of uploading it again.
      reparseWith(optionsForAnotherAccount(p.options), id);
    } else {
      setUndone(false);
      preview.mutate({ file, accountId: id }, { onSuccess: applyPreview });
    }
  }

  function remove() {
    if (p && !committed) discard.mutate(p.staging_id);
    onRemove();
  }

  function commitNow(auto: boolean, verified = false) {
    if (!accountId || !p) return;
    const rowDecisions = Object.entries(decisions).map(([rowIndex, decision]) => ({
      source_row_index: Number(rowIndex),
      decision,
    }));
    commit.mutate(
      { stagingId: p.staging_id, accountId, rowDecisions, auto, verified },
      {
        onSuccess: (result) => {
          setCommitted(result);
          setSeenInHistory(false); // the list of imports doesn't know it yet
          setAutoImported(auto);
          setReviewOpen(false);
          onDone();
          // imported by hand (maybe taught, maybe "don't ask again"): the other files may know their kind now
          if (!auto) noteLearned();
        },
        onError: (error) => {
          if (!auto) return;
          // e.g. a file of the same month was imported meanwhile: show the fresh preview
          setManual(true);
          setAutoRefused((error as Error).message);
          commit.reset();
          reparseWith(p.options);
        },
      }
    );
  }

  // Another file was imported by hand meanwhile — taught, confirmed, or just
  // the first of its kind: read this one again as files of its kind are read
  // now (once), unless the user chose its account or columns themselves.
  const learned = useLearnedVersion();
  const knownLearned = useRef(learned);
  const accountChosen = useRef(false);
  useEffect(() => {
    if (learned === knownLearned.current) return;
    if (committed || undone || formOptions || accountChosen.current) {
      knownLearned.current = learned;
      return;
    }
    if (!p || preview.isPending || reparse.isPending || commit.isPending || recognize.isPending) return;
    knownLearned.current = learned;
    setReviewOpen(false);
    recognize.mutate(p.staging_id, {
      onSuccess: (data) => {
        setManual(false); // an automatic choice of the only account doesn't count
        applyPreview(data);
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [learned, p, committed, undone, formOptions, preview.isPending, reparse.isPending, commit.isPending]);

  // Recognized and nothing to check: import without asking. A kind of file
  // not checked yet, or one with something to look at, opens the review.
  useEffect(() => {
    if (!p || committed || commit.isPending) return;
    // a PDF nothing was read from opens it too: there it can be taught
    const teachable = p.page_count > 0 && p.transaction_count === 0;
    if (p.review_reasons.length > 0 && (p.account_id !== null || teachable) && !reviewDismissed && hasOriginal(p)) {
      setReviewOpen(true);
    } else if (p.auto_import && autoImport && !manual && p.review_reasons.length === 0) {
      commitNow(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p]);

  // The file is not imported any more: back to choosing an account.
  function forgetImport() {
    commit.reset();
    setCommitted(undefined);
    setSeenInHistory(false);
    setPreview(undefined);
    setManual(true);
    setUndone(true);
    setPickAccount(true);
  }

  // The card outlives its import: it may be removed in the list below or in
  // another window, and its number may belong to another import since. Once
  // the list has shown this card's import, its absence means it is gone —
  // "Undo" must never remove whatever has that number now.
  const stillImported = committed !== undefined && isSameImport(committed, history.data);
  useEffect(() => {
    if (!committed || !history.data || history.isFetching) return;
    if (stillImported) setSeenInHistory(true);
    else if (seenInHistory) forgetImport();
    // (not seen yet: the list is from before this import and is being read again)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [committed, history.data, history.isFetching, stillImported, seenInHistory]);

  function undo() {
    if (!committed || !stillImported) return;
    removal.mutate(committed.import_id, {
      onSuccess: () => {
        forgetImport();
        onDone();
      },
    });
  }

  const duplicateRows = useMemo(() => (p ? p.row_classifications.filter((r) => r.status !== "new") : []), [p]);
  const rowsByIndex = useMemo(() => {
    const map = new Map<number, ParsedTransactionPreview>();
    p?.transactions.forEach((t) => map.set(t.source_row_index, t));
    return map;
  }, [p]);

  // Live summary reflecting the user's current keep/skip choices.
  const willImportCount = p ? p.new_count + Object.values(decisions).filter((d) => d === "keep").length : 0;
  const willSkipCount = p ? Object.values(decisions).filter((d) => d === "skip").length : 0;
  const needsWarningConfirmation = p ? p.warning_count > 0 || p.unusable_row_count > 0 : false;
  const importable = p && p.account_id !== null && !p.ambiguous && !p.has_errors;
  const busy = preview.isPending || reparse.isPending || recognize.isPending;
  const autoPending = commit.isPending && p?.auto_import && !manual;

  const requestError = (preview.error ?? reparse.error ?? recognize.error ?? removal.error) as Error | null;
  const choosingAccount = !committed && !unreadable && (pickAccount || (p !== undefined && p.account_id === null) || undone);
  const accountName = p?.account_name ?? "";

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-medium text-ink truncate">{file.name}</div>
          {p && !unreadable && (
            <div className="text-xs text-ink-muted mt-0.5">
              {p.document_type === "credit_card_statement" ? t("imports.docType.cardStatement") : t("imports.docType.bank")}
              {p.detected_layout === "user_template"
                ? t("importCard.taughtLayout")
                : p.detected_layout && !p.detected_layout.startsWith("generic_") && t("importCard.layout", { layout: p.detected_layout })}
              {p.period_start && p.period_end && ` · ${formatDate(p.period_start)} – ${formatDate(p.period_end)}`}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {committed && <Badge tone="income">{t("importCard.imported")}</Badge>}
          {busy && <Badge tone="neutral">{t("importCard.parsing")}</Badge>}
          {(requestError || unreadable) && <Badge tone="danger">{t("importCard.error")}</Badge>}
          {!commit.isPending && (
            <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={remove} title={t("importCard.removeTitle")}>
              {committed ? t("common.close") : t("common.remove")}
            </Button>
          )}
        </div>
      </div>

      {!committed && !autoPending && !unreadable && (p || undone) && (
        <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
          {choosingAccount ? (
            <>
              <span className="text-ink-muted">{undone ? t("importCard.undone") : t("importCard.whichAccount")}</span>
              <AccountSelect accounts={accounts ?? []} value={undefined} onChange={changeAccount} disabled={busy} />
              {pickAccount && p?.account_id != null && (
                <button
                  type="button"
                  className="text-xs text-ink-muted underline underline-offset-2"
                  onClick={() => setPickAccount(false)}
                >
                  {t("common.cancel")}
                </button>
              )}
            </>
          ) : (
            p?.account_id != null && (
              <>
                <span className="text-ink-muted">
                  {t("importCard.account")} <span className="font-medium text-ink">{p.account_name}</span>
                  {p.account_recognized === "iban" && !manual && t("importCard.recognizedByIban")}
                  {p.account_recognized === "history" && !manual && t("importCard.recognizedByHistory")}
                  {p.account_recognized === "format" && !manual && t("importCard.recognizedByFormat")}
                  {p.account_recognized === "replaced" && !manual && t("importCard.recognizedAsReplacedCard")}
                </span>
                <button
                  type="button"
                  className="text-xs text-accent-strong underline underline-offset-2"
                  disabled={busy}
                  onClick={() => setPickAccount(true)}
                >
                  {t("importCard.otherAccount")}
                </button>
              </>
            )
          )}
          {p && hasOriginal(p) && !choosingAccount && (
            <button
              type="button"
              className="text-xs text-accent-strong underline underline-offset-2"
              onClick={() => setReviewOpen(true)}
            >
              {t("importCard.review")}
            </button>
          )}
          {p && p.available_columns.length > 0 && !showMapping && !choosingAccount && (
            <button
              type="button"
              className="text-xs text-accent-strong underline underline-offset-2"
              onClick={() => setShowMapping(true)}
            >
              {t("importCard.adjust")}
            </button>
          )}
        </div>
      )}

      {autoRefused && !committed && (
        <div className="mt-3 rounded-md bg-warning-soft px-3 py-2 text-xs text-warning">{autoRefused}</div>
      )}

      {requestError && (
        <div className="mt-3 rounded-md bg-danger-soft border border-danger/20 px-3 py-2 text-xs text-danger">
          {requestError.message}
        </div>
      )}

      {p && !committed && !autoPending && (
        <div className="mt-3 space-y-3">
          <ImportIssuesList issues={p.issues} />

          {unreadable && p.page_count > 0 && (
            <div className="flex flex-wrap items-center gap-3 text-xs text-ink-muted">
              <Button variant="secondary" className="!py-1 text-xs" onClick={() => setReviewOpen(true)}>
                {t("teach.openForFile")}
              </Button>
              <span>{t("teach.openForFileHint")}</span>
            </div>
          )}

          {showMapping && !unreadable && (
            <ColumnMappingForm
              key={p.staging_id + JSON.stringify(p.options)}
              preview={p}
              isPending={reparse.isPending}
              onSubmit={(options) => {
                setFormOptions(true);
                reparseWith(options);
              }}
              onCancel={p.ambiguous ? undefined : () => setShowMapping(false)}
            />
          )}
        </div>
      )}

      {importable && !committed && !autoPending && (
        <div className="mt-4 space-y-3">
          <ImportSummaryCounts
            newCount={p.new_count}
            exactCount={p.exact_duplicate_count}
            possibleCount={p.possible_duplicate_count}
            needsReviewCount={p.needs_review_count}
          />

          {p.total_check?.ok && (
            <div className="text-xs text-income">
              {p.total_check.kind === "balance" ? t("importCard.balanceOk") : t("importCard.statementTotalOk")}
            </div>
          )}
          {p.total_check && !p.total_check.ok && p.total_check.kind === "statement_total" && (
            <div className="text-xs text-ink-muted">
              {t("importCard.statementTotalOff", { amount: formatMoney(Math.abs(p.total_check.difference_minor)) })}
            </div>
          )}

          {p.unusable_row_count > 0 && (
            <div className="text-xs text-warning">
              {tn("importCard.unusable", p.unusable_row_count)}
            </div>
          )}

          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {p.transactions.length > 0 && (
              <button
                type="button"
                onClick={() => setShowRows((v) => !v)}
                aria-expanded={showRows}
                className="text-xs text-accent-strong underline underline-offset-2"
              >
                {showRows ? t("importCard.hideRows") : tn("importCard.showRows", p.transactions.length)}
              </button>
            )}
            {duplicateRows.length > 0 && (
              <button
                type="button"
                onClick={() => setShowDetails((v) => !v)}
                aria-expanded={showDetails}
                className="text-xs text-accent-strong underline underline-offset-2"
              >
                {showDetails ? t("importCard.hideDuplicates") : t("importCard.reviewDuplicates")}
              </button>
            )}
          </div>
          {showRows && <ParsedRows rows={p.transactions} />}
          {showDetails && (
            <div className="space-y-2">
              {duplicateRows.map((row) => (
                <DuplicateRowCard
                  key={row.source_row_index}
                  row={row}
                  parsedTx={rowsByIndex.get(row.source_row_index)}
                  decision={decisions[row.source_row_index] ?? defaultDecisionFor(row.status)}
                  onDecisionChange={(d) => setDecisions((prev) => ({ ...prev, [row.source_row_index]: d }))}
                />
              ))}
            </div>
          )}

          <div className="rounded-md bg-surface-sunken px-3 py-2 text-xs text-ink-muted">
            {willImportCount === 0 && willSkipCount > 0
              ? tn("importCard.allKnown", willSkipCount, { account: accountName })
              : (
                <>
                  {tn("importCard.willImport", willImportCount, { account: accountName })}
                  {willSkipCount > 0 && t("importCard.andSkip", { count: willSkipCount })}.
                </>
              )}
          </div>

          {needsWarningConfirmation && (
            <label className="flex items-start gap-2 text-xs text-ink">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={warningsConfirmed}
                onChange={(e) => setWarningsConfirmed(e.target.checked)}
              />
              {t("importCard.confirmWarnings")}
            </label>
          )}

          <Button
            variant="primary"
            disabled={commit.isPending || busy || willImportCount + willSkipCount === 0 || (needsWarningConfirmation && !warningsConfirmed)}
            onClick={() => commitNow(false)}
          >
            {commit.isPending ? t("importCard.importing") : t("importCard.import")}
          </Button>
          {commit.isError && <div className="text-xs text-danger">{(commit.error as Error).message}</div>}
        </div>
      )}

      {autoPending && <div className="mt-3 text-xs text-ink-muted">{t("importCard.importingInto", { account: accountName })}</div>}

      {committed && (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className="text-income">
            {autoImported
              ? tn("importCard.autoDone", committed.transactions_created, { account: accountName })
              : tn("importCard.done", committed.transactions_created)}
            {committed.rows_skipped > 0 && t("importCard.skipped", { count: committed.rows_skipped })}
            {committed.transactions_enriched > 0 && tn("importCard.enriched", committed.transactions_enriched)}.
          </span>
          <button
            type="button"
            className="text-ink-muted underline underline-offset-2 hover:text-ink disabled:opacity-50"
            disabled={removal.isPending || !stillImported}
            onClick={undo}
            title={t("importCard.undoTitle")}
          >
            {removal.isPending ? t("imports.removing") : t("importCard.undo")}
          </button>
        </div>
      )}
      {reviewOpen && p && (
        <ImportReview
          preview={p}
          importing={commit.isPending}
          canImport={Boolean(importable) && !committed && willImportCount + willSkipCount > 0}
          onImport={(dontAskAgain) => commitNow(false, dontAskAgain)}
          onTeach={p.page_count > 0 ? teach : undefined}
          teaching={reparse.isPending}
          accountPicker={
            <span className="flex items-center gap-2 text-xs text-ink-muted">
              {t("importCard.whichAccount")}
              <AccountSelect accounts={accounts ?? []} value={undefined} onChange={changeAccount} disabled={busy} />
            </span>
          }
          onClose={() => {
            setReviewOpen(false);
            setReviewDismissed(true);
          }}
        />
      )}
    </Card>
  );
}

function hasOriginal(p: ImportPreview): boolean {
  return p.page_count > 0 || p.source_rows.length > 0;
}

/** The bookings as the app read them — to check dates, signs and amounts
 * (e.g. after choosing a date format or decimal separator) before importing. */
function ParsedRows({ rows }: { rows: ParsedTransactionPreview[] }) {
  const { t, tn } = useI18n();
  const shown = rows.slice(0, 50);
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-xs">
        <thead className="text-ink-muted">
          <tr className="border-b border-border">
            <th className="text-left font-medium px-3 py-1.5">{t("col.date")}</th>
            <th className="text-left font-medium px-3 py-1.5">{t("col.description")}</th>
            <th className="text-right font-medium px-3 py-1.5">{t("col.amount")}</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((row) => (
            <tr key={row.source_row_index} className="border-b border-border last:border-0">
              <td className="px-3 py-1.5 whitespace-nowrap text-ink-muted">
                {row.parsed_date ? formatDate(row.parsed_date) : <span className="text-warning">{row.original_date_text ?? "—"}</span>}
              </td>
              <td className="px-3 py-1.5 text-ink max-w-[360px] truncate" title={row.original_description ?? ""}>
                {row.original_description ?? "—"}
              </td>
              <td className={`px-3 py-1.5 text-right tabular-nums whitespace-nowrap ${
                row.parsed_amount_minor === null ? "text-warning" : row.parsed_amount_minor < 0 ? "text-expense" : "text-income"
              }`}>
                {row.parsed_amount_minor === null
                  ? row.original_amount_text ?? "—"
                  : formatSignedMoney(row.parsed_amount_minor, row.parsed_currency ?? "EUR")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > shown.length && (
        <div className="px-3 py-1.5 text-xs text-ink-muted border-t border-border">
          {tn("importCard.moreRows", rows.length - shown.length)}
        </div>
      )}
    </div>
  );
}

function AccountSelect({
  accounts,
  value,
  onChange,
  disabled,
}: {
  accounts: Account[];
  value: number | undefined;
  onChange: (id: number) => void;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  return (
    <select
      aria-label={t("importCard.targetAccount")}
      className="text-sm border border-border-strong rounded-md px-2.5 py-2 bg-surface text-ink"
      value={value ?? ""}
      disabled={disabled}
      onChange={(e) => onChange(Number(e.target.value))}
    >
      {accounts.length === 0 && <option value="">{t("importCard.noAccounts")}</option>}
      {accounts.length > 0 && value === undefined && <option value="">{t("importCard.chooseAccount")}</option>}
      {accounts.map((a) => (
        <option key={a.id} value={a.id}>
          {a.name}
          {a.account_type === "credit_card" ? t("importCard.creditCardSuffix") : ""}
        </option>
      ))}
    </select>
  );
}
