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
import { isSameImport, noteLearned, uploadSlot, useLearnedVersion, type CardSnapshot } from "../../state/importQueue";
import type {
  Account,
  ImportPreview,
  ParseOptions,
  PdfTemplate,
  ParsedTransactionPreview,
  RowDecisionValue,
} from "../../types";

function defaultDecisionFor(status: string): RowDecisionValue {
  return status === "exact_duplicate" ? "skip" : "keep";
}

/** What the user chose for the preview shown. A new preview (another
 * account, other columns) starts over. */
interface Choices {
  for: ImportPreview | undefined;
  decisions: Record<number, RowDecisionValue>;
  warningsConfirmed: boolean;
  showMapping: boolean;
}

function initialChoices(preview: ImportPreview | undefined): Choices {
  const decisions: Record<number, RowDecisionValue> = {};
  for (const row of preview?.row_classifications ?? []) {
    if (row.status !== "new") decisions[row.source_row_index] = defaultDecisionFor(row.status);
  }
  return {
    for: preview,
    decisions,
    warningsConfirmed: false,
    showMapping: Boolean(preview && preview.ambiguous && preview.available_columns.length > 0),
  };
}

/** The file is not imported (any more): back to choosing an account. */
const NOT_IMPORTED: CardSnapshot = {
  error: undefined,
  commitError: undefined,
  committed: undefined,
  seenInHistory: false,
  preview: undefined,
  manual: true,
  undone: true,
};

export function ImportFileCard({
  file,
  autoImport,
  snapshot,
  onSnapshot,
  onRemove,
  reviewOpen,
  reviewElsewhere,
  onReview,
}: {
  file: File;
  /** import right away when the account is recognized and the preview shows nothing to check */
  autoImport: boolean;
  /** what the card has reached and is doing (see state/importQueue) */
  snapshot: CardSnapshot;
  /** false: the file is not in the queue any more */
  onSnapshot: (patch: CardSnapshot) => boolean | void;
  onRemove: () => void;
  /** this file's import review is open */
  reviewOpen: boolean;
  /** another file's is: this one waits for its turn */
  reviewElsewhere: boolean;
  onReview: (open: boolean) => void;
}) {
  const { t, tn } = useI18n();
  const { data: accounts } = useAccounts();

  // Everything a request changes is kept with the file in the queue, not in
  // this component: its answer also arrives when the page was left
  // meanwhile, and the card shows it when the page is opened again.
  const { preview: p, committed } = snapshot;
  const seenInHistory = Boolean(snapshot.seenInHistory);
  // The user took over: chose or changed the account, or undid an import.
  // Nothing is then imported without their click.
  const manual = Boolean(snapshot.manual);
  const undone = Boolean(snapshot.undone);
  const formOptions = Boolean(snapshot.formOptions);
  const waiting = snapshot.busy === "waiting";
  const busy = snapshot.busy === "reading";
  const importing = snapshot.busy === "importing";
  const undoing = snapshot.busy === "undoing";

  const [showDetails, setShowDetails] = useState(false);
  const [showRows, setShowRows] = useState(false);
  const [pickAccount, setPickAccount] = useState(false);
  const [chosen, setChosen] = useState<Choices>(() => initialChoices(p));
  const choices = chosen.for === p ? chosen : initialChoices(p);
  const { decisions, warningsConfirmed, showMapping } = choices;
  const choose = (patch: Partial<Choices>) => setChosen({ ...choices, ...patch });

  const preview = usePreviewImport();
  const reparse = useReparseImport();
  const recognize = useRecognizeImport();
  const discard = useDiscardStagedImport();
  const commit = useCommitImport();
  const removal = useRemoveImport();
  const history = useImportHistory();
  const started = useRef(false);
  // (as snapshot.busy, but known at once: not only after the next render)
  const sending = useRef(false);

  /** Sends one request of this card and keeps its outcome with the file:
   * `done` / `failed` say what it changes. Resolves to whether it worked. */
  function request<T>(
    doing: NonNullable<CardSnapshot["busy"]>,
    send: () => Promise<T>,
    done: (result: T) => CardSnapshot,
    failed: (message: string) => CardSnapshot = (error) => ({ error })
  ): Promise<boolean> {
    sending.current = true;
    onSnapshot({ busy: doing, error: undefined, commitError: undefined });
    return send().then(
      (result) => {
        sending.current = false;
        onSnapshot({ busy: undefined, ...done(result) });
        return true;
      },
      (error: Error) => {
        sending.current = false;
        onSnapshot({ busy: undefined, ...failed(error.message) });
        return false;
      }
    );
  }

  // Read the file right away — when its turn comes: of many files dropped at
  // once, a few are uploaded and read at a time (state/importQueue). The
  // backend recognizes the file's account if it can.
  useEffect(() => {
    if (started.current || snapshot.preview || snapshot.committed || snapshot.undone || snapshot.busy) return;
    started.current = true;
    onSnapshot({ busy: "waiting", error: undefined });
    void uploadSlot().then((release) => {
      if (onSnapshot({ busy: "reading" }) === false) return release(); // removed while it waited
      preview
        .mutateAsync({ file })
        .finally(release)
        .then(
          (data) => {
            // removed while it was read: nobody is left to import it
            if (onSnapshot({ busy: undefined, preview: data }) === false) discard.mutate(data.staging_id);
          },
          (error: Error) => void onSnapshot({ busy: undefined, error: error.message })
        );
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const accountId = p?.account_id ?? undefined;
  // A file nothing could be read from: no point asking for its account.
  const unreadable = p !== undefined && p.has_errors && p.transaction_count === 0;

  /** Reads the uploaded file again: for another account, with other options. */
  function readAgain(staged: ImportPreview, options: ParseOptions, targetAccountId: number | null) {
    return request(
      "reading",
      () => reparse.mutateAsync({ stagingId: staged.staging_id, accountId: targetAccountId, options }),
      (data) => ({ preview: data })
    );
  }

  function reparseWith(options: ParseOptions, targetAccountId = accountId) {
    if (p && targetAccountId) void readAgain(p, options, targetAccountId);
  }

  // The user taught the reader in the review: read the file again with it
  // (also before an account is chosen).
  function teach(template: PdfTemplate | null) {
    if (p) void readAgain(p, { ...p.options, pdf_template: template }, p.account_id);
  }

  // For another account the app decides anew about inverting the amounts —
  // unless the user chose it in the column/format dialog.
  function optionsForAnotherAccount(options: ParseOptions): ParseOptions {
    return formOptions ? options : { ...options, invert_signs: null };
  }

  // Not recognized, but there is only one account: that one (confirmed by the user's click).
  const onlyAccount = accounts?.length === 1 ? accounts[0].id : undefined;
  useEffect(() => {
    if (p && p.account_id === null && !unreadable && onlyAccount !== undefined && !snapshot.busy && !manual) {
      onSnapshot({ manual: true });
      reparseWith(optionsForAnotherAccount(p.options), onlyAccount);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p, onlyAccount]);

  function changeAccount(id: number) {
    setPickAccount(false);
    onSnapshot({ manual: true, accountChosen: true });
    if (p && !committed) {
      // Duplicate detection depends on the account: re-classify the already
      // uploaded file instead of uploading it again.
      reparseWith(optionsForAnotherAccount(p.options), id);
    } else {
      // (the import was undone: the file is uploaded again)
      void request("reading", () => preview.mutateAsync({ file, accountId: id }), (data) => ({ preview: data, undone: false }));
    }
  }

  function remove() {
    if (p && !committed) discard.mutate(p.staging_id);
    onReview(false);
    onRemove();
  }

  function commitNow(auto: boolean, verified = false) {
    if (!accountId || !p || snapshot.busy || sending.current) return;
    const staged = p;
    const rowDecisions = Object.entries(decisions).map(([rowIndex, decision]) => ({
      source_row_index: Number(rowIndex),
      decision,
    }));
    void request(
      "importing",
      () => commit.mutateAsync({ stagingId: staged.staging_id, accountId, rowDecisions, auto, verified }),
      // (the list of imports doesn't know it yet)
      (result) => ({ committed: result, seenInHistory: false, autoImported: auto }),
      (message) => (auto ? { manual: true, autoRefused: message } : { commitError: message })
    ).then((imported) => {
      if (imported) {
        onReview(false);
        // imported by hand (maybe taught, maybe "don't ask again"): the other files may know their kind now
        if (!auto) noteLearned();
      } else if (auto) {
        // e.g. a file of the same month was imported meanwhile: show the fresh preview
        void readAgain(staged, staged.options, accountId);
      }
    });
  }

  // Another file was imported by hand meanwhile — taught, confirmed, or just
  // the first of its kind: read this one again as files of its kind are read
  // now (once), unless the user chose its account or columns themselves.
  const learned = useLearnedVersion();
  const knownLearned = useRef(learned);
  useEffect(() => {
    if (learned === knownLearned.current) return;
    if (committed || undone || formOptions || snapshot.accountChosen) {
      knownLearned.current = learned;
      return;
    }
    if (!p || snapshot.busy) return;
    knownLearned.current = learned;
    onReview(false);
    const stagingId = p.staging_id;
    // (manual: an automatic choice of the only account doesn't count)
    void request("reading", () => recognize.mutateAsync(stagingId), (data) => ({ preview: data, manual: false }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [learned, p, committed, undone, formOptions, snapshot.busy]);

  // A kind of file not checked yet, or one with something to look at, opens
  // the review (a PDF nothing was read from too: there it can be taught) —
  // when no other file's review is open; then it waits for that to close.
  const wantsReview =
    p !== undefined &&
    !committed &&
    p.review_reasons.length > 0 &&
    (p.account_id !== null || (p.page_count > 0 && p.transaction_count === 0)) &&
    !snapshot.reviewDismissed &&
    hasOriginal(p);
  useEffect(() => {
    if (wantsReview && !reviewOpen && !reviewElsewhere && !snapshot.busy) onReview(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p, wantsReview, reviewElsewhere]);

  // Recognized and nothing to check: import without asking.
  useEffect(() => {
    if (!p || committed || snapshot.busy || wantsReview) return;
    if (p.auto_import && autoImport && !manual && p.review_reasons.length === 0) commitNow(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p]);

  // The card outlives its import: it may be removed in the list below or in
  // another window, and its number may belong to another import since. Once
  // the list has shown this card's import, its absence means it is gone —
  // "Undo" must never remove whatever has that number now.
  const stillImported = committed !== undefined && isSameImport(committed, history.data);
  useEffect(() => {
    if (!committed || !history.data || history.isFetching) return;
    if (stillImported) {
      if (!seenInHistory) onSnapshot({ seenInHistory: true });
    } else if (seenInHistory) onSnapshot(NOT_IMPORTED);
    // (not seen yet: the list is from before this import and is being read again)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [committed, history.data, history.isFetching, stillImported, seenInHistory]);

  function undo() {
    if (!committed || !stillImported || snapshot.busy) return;
    const importId = committed.import_id;
    void request("undoing", () => removal.mutateAsync(importId), () => NOT_IMPORTED);
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
  const autoPending = importing && p?.auto_import && !manual;

  const requestError = snapshot.error;
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
          {waiting && <Badge tone="neutral">{t("importCard.waiting")}</Badge>}
          {busy && <Badge tone="neutral">{t("importCard.parsing")}</Badge>}
          {(requestError || unreadable) && <Badge tone="danger">{t("importCard.error")}</Badge>}
          {!importing && (
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
              onClick={() => onReview(true)}
            >
              {t("importCard.review")}
            </button>
          )}
          {p && p.available_columns.length > 0 && !showMapping && !choosingAccount && (
            <button
              type="button"
              className="text-xs text-accent-strong underline underline-offset-2"
              onClick={() => choose({ showMapping: true })}
            >
              {t("importCard.adjust")}
            </button>
          )}
        </div>
      )}

      {snapshot.autoRefused && !committed && (
        <div className="mt-3 rounded-md bg-warning-soft px-3 py-2 text-xs text-warning">{snapshot.autoRefused}</div>
      )}

      {requestError && (
        <div className="mt-3 rounded-md bg-danger-soft border border-danger/20 px-3 py-2 text-xs text-danger">
          {requestError}
        </div>
      )}

      {p && !committed && !autoPending && (
        <div className="mt-3 space-y-3">
          <ImportIssuesList issues={p.issues} />

          {unreadable && p.page_count > 0 && (
            <div className="flex flex-wrap items-center gap-3 text-xs text-ink-muted">
              <Button variant="secondary" className="!py-1 text-xs" onClick={() => onReview(true)}>
                {t("teach.openForFile")}
              </Button>
              <span>{t("teach.openForFileHint")}</span>
            </div>
          )}

          {showMapping && !unreadable && (
            <ColumnMappingForm
              key={p.staging_id + JSON.stringify(p.options)}
              preview={p}
              isPending={busy}
              onSubmit={(options) => {
                onSnapshot({ formOptions: true });
                reparseWith(options);
              }}
              onCancel={p.ambiguous ? undefined : () => choose({ showMapping: false })}
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
                  onDecisionChange={(d) => choose({ decisions: { ...decisions, [row.source_row_index]: d } })}
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
                onChange={(e) => choose({ warningsConfirmed: e.target.checked })}
              />
              {t("importCard.confirmWarnings")}
            </label>
          )}

          <Button
            variant="primary"
            disabled={importing || busy || willImportCount + willSkipCount === 0 || (needsWarningConfirmation && !warningsConfirmed)}
            onClick={() => commitNow(false)}
          >
            {importing ? t("importCard.importing") : t("importCard.import")}
          </Button>
          {snapshot.commitError && <div className="text-xs text-danger">{snapshot.commitError}</div>}
        </div>
      )}

      {autoPending && <div className="mt-3 text-xs text-ink-muted">{t("importCard.importingInto", { account: accountName })}</div>}

      {committed && (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className="text-income">
            {snapshot.autoImported
              ? tn("importCard.autoDone", committed.transactions_created, { account: accountName })
              : tn("importCard.done", committed.transactions_created)}
            {committed.rows_skipped > 0 && t("importCard.skipped", { count: committed.rows_skipped })}
            {committed.transactions_enriched > 0 && tn("importCard.enriched", committed.transactions_enriched)}.
          </span>
          <button
            type="button"
            className="text-ink-muted underline underline-offset-2 hover:text-ink disabled:opacity-50"
            disabled={undoing || !stillImported}
            onClick={undo}
            title={t("importCard.undoTitle")}
          >
            {undoing ? t("imports.removing") : t("importCard.undo")}
          </button>
        </div>
      )}
      {reviewOpen && p && (
        <ImportReview
          preview={p}
          importing={importing}
          error={snapshot.commitError ?? requestError}
          canImport={Boolean(importable) && !committed && willImportCount + willSkipCount > 0}
          onImport={(dontAskAgain) => commitNow(false, dontAskAgain)}
          onTeach={p.page_count > 0 ? teach : undefined}
          teaching={busy}
          accountPicker={
            <span className="flex items-center gap-2 text-xs text-ink-muted">
              {t("importCard.whichAccount")}
              <AccountSelect accounts={accounts ?? []} value={undefined} onChange={changeAccount} disabled={busy} />
            </span>
          }
          onClose={() => {
            onReview(false);
            onSnapshot({ reviewDismissed: true });
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
