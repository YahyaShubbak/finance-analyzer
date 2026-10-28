import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import clsx from "clsx";
import { Button } from "../ui";
import { stagedPageUrl } from "../../api/imports";
import { formatDate, formatMoney, formatSignedMoney } from "../../lib/format";
import { useI18n } from "../../i18n/useI18n";
import type { MessageKey } from "../../i18n/core";
import type { ImportPreview, LayoutLine, ParsedTransactionPreview, PdfBox, PdfTemplate } from "../../types";
import { EMPTY_TEMPLATE, columnsFrom, isUsable, normalizeLine, suggestRoles, type WordRole } from "../../lib/pdfTemplate";
import { TeachReader } from "./TeachReader";

/** Most statements are A4: 595 points wide. */
const A4_WIDTH_PT = 595;

const ROLE_STYLE: Record<string, string> = {
  booking: "border-income bg-income/15",
  detail: "border-income/40 bg-income/5",
  unreadable: "border-warning bg-warning/25",
  balance: "border-accent bg-accent/10",
  ignored: "border-ink-faint bg-ink/10",
  example: "border-accent-strong bg-accent/25",
  text: "border-transparent hover:border-accent/60 hover:bg-accent/5",
};

function isPdfBox(location: ParsedTransactionPreview["location"]): location is PdfBox {
  return location !== null && "page" in location;
}

/**
 * The import review: the original on the left (PDF pages, or the
 * spreadsheet's rows), what was read on the right, linked line by line.
 * Opens by itself for a kind of file not checked yet or when something
 * needs a look; "don't ask again" lets files of this kind import themselves.
 */
export function ImportReview({
  preview,
  importing,
  canImport,
  onImport,
  onClose,
  onTeach,
  teaching: applying = false,
  accountPicker,
}: {
  preview: ImportPreview;
  importing: boolean;
  canImport: boolean;
  onImport: (dontAskAgain: boolean) => void;
  onClose: () => void;
  /** read the file again with a taught template (null: with the built-in readers) */
  onTeach?: (template: PdfTemplate | null) => void;
  /** a taught template is being applied */
  teaching?: boolean;
  /** shown instead of the import button while no account is chosen */
  accountPicker?: ReactNode;
}) {
  const { t, tn } = useI18n();
  const [selected, setSelected] = useState<number | null>(null); // source_row_index
  const [page, setPage] = useState(0);
  const [zoom, setZoom] = useState(1.5);
  // the page fills the width of the left half when the review opens
  const pageArea = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const width = pageArea.current?.clientWidth;
    if (width) setZoom(Math.min(3, Math.max(0.5, Math.floor(((width - 28) / A4_WIDTH_PT) * 20) / 20)));
  }, []);
  const [dontAskAgain, setDontAskAgain] = useState(false);
  const closeButton = useRef<HTMLButtonElement>(null);
  const rowRefs = useRef(new Map<number, HTMLElement>());
  const onCloseRef = useRef(onClose);
  useLayoutEffect(() => {
    onCloseRef.current = onClose;
  });

  const dialog = useRef<HTMLDivElement>(null);

  // Tab stays inside the dialog; on close the focus goes back to the button that opened it.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    closeButton.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCloseRef.current();
      if (e.key !== "Tab" || !dialog.current) return;
      const focusable = [
        ...dialog.current.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        ),
      ].filter((el) => el.offsetParent !== null);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const inside = dialog.current.contains(document.activeElement);
      if (e.shiftKey && (document.activeElement === first || !inside)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (document.activeElement === last || !inside)) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (opener?.isConnected) opener.focus();
    };
  }, []);

  // Teaching the reader (PDFs): opens by itself when nothing was read.
  const isPdf = preview.page_count > 0;
  const taught = preview.options.pdf_template ?? null;
  const [teach, setTeach] = useState(isPdf && onTeach !== undefined && preview.transactions.length === 0);
  const [template, setTemplate] = useState<PdfTemplate>(
    () =>
      taught ?? {
        ...EMPTY_TEMPLATE,
        document_type: preview.document_type === "credit_card_statement" ? "credit_card_statement" : "bank_statement",
      }
  );
  const [changed, setChanged] = useState(false);
  // how the file was read before this teaching: "cancel" goes back to it
  const [startTemplate, setStartTemplate] = useState<PdfTemplate | null>(taught);
  const [appliedHere, setAppliedHere] = useState(false);
  const [finished, setFinished] = useState(false);
  const [picked, setPicked] = useState<LayoutLine | null>(null);
  const [example, setExample] = useState<LayoutLine | null>(null);
  const [roles, setRoles] = useState<WordRole[]>([]);

  function changeTemplate(next: PdfTemplate) {
    setTemplate(next);
    setChanged(true);
  }

  // read again shortly after each change (not on every keystroke-like burst of clicks)
  useEffect(() => {
    if (!changed || !onTeach || !isUsable(template)) return;
    const timer = setTimeout(() => {
      setChanged(false);
      setAppliedHere(true);
      onTeach(template);
    }, 400);
    return () => clearTimeout(timer);
  }, [changed, template, onTeach]);

  function useAsExample(line: LayoutLine) {
    const suggested = suggestRoles(line.words);
    setExample(line);
    setRoles(suggested);
    changeTemplate({ ...template, columns: columnsFrom(line.words, suggested) });
  }

  function changeRoles(next: WordRole[]) {
    if (!example) return;
    setRoles(next);
    changeTemplate({ ...template, columns: columnsFrom(example.words, next) });
  }

  function discardTemplate() {
    setExample(null);
    setRoles([]);
    setPicked(null);
    setChanged(false);
    setTemplate({ ...EMPTY_TEMPLATE, document_type: template.document_type });
    setAppliedHere(true);
    onTeach?.(null);
  }

  /** Done: what was taught stays (and is kept with the import); the result shows on the right. */
  function finishTeaching() {
    if (changed && isUsable(template) && onTeach) {
      setChanged(false);
      setAppliedHere(true);
      onTeach(template);
    }
    setTeach(false);
    setPicked(null);
    setFinished(true);
  }

  /** Cancel: read the file as before teaching. */
  function cancelTeaching() {
    setTeach(false);
    setPicked(null);
    setExample(null);
    setRoles([]);
    setChanged(false);
    setFinished(false);
    if (appliedHere && onTeach) {
      setTemplate(startTemplate ?? { ...EMPTY_TEMPLATE, document_type: template.document_type });
      setAppliedHere(false);
      onTeach(startTemplate);
    }
  }

  // how a line shows on the page while teaching
  const ignored = useMemo(() => new Set(template.ignore.map(normalizeLine)), [template.ignore]);
  const labelled = useMemo(
    () => new Set(Object.values(template.labels).filter(Boolean).map((text) => normalizeLine(text!))),
    [template.labels]
  );
  function teachStyle(line: LayoutLine): string {
    if (example?.index === line.index) return "example";
    const normalized = normalizeLine(line.text);
    if (ignored.has(normalized)) return "ignored";
    if (labelled.has(normalized)) return "balance";
    return line.role;
  }

  const bookingsByIndex = useMemo(
    () => new Map(preview.transactions.map((tx) => [tx.source_row_index, tx])),
    [preview.transactions]
  );
  const unreadable = preview.layout_lines.filter((line) => line.role === "unreadable").length;

  function select(index: number, fromOriginal: boolean) {
    setSelected(index);
    const tx = bookingsByIndex.get(index);
    if (!fromOriginal && tx && isPdfBox(tx.location)) setPage(tx.location.page);
    if (fromOriginal) rowRefs.current.get(index)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  const check = preview.total_check;
  return (
    <div className="fixed inset-0 z-50 bg-ink/40 flex items-stretch" role="presentation">
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="import-review-title"
        className="bg-surface w-full flex flex-col overflow-hidden"
      >
        <div className="flex flex-wrap items-start justify-between gap-3 px-5 py-3 border-b border-border">
          <div className="min-w-0">
            <h2 id="import-review-title" className="text-sm font-semibold text-ink truncate">
              {t("review.importTitle", { file: preview.filename })}
            </h2>
            <div className="text-xs text-ink-muted mt-0.5 flex flex-wrap gap-x-3">
              <span>{tn("review.bookingsRead", preview.transactions.length)}</span>
              {unreadable > 0 && <span className="text-warning">{tn("review.unreadableLines", unreadable)}</span>}
              {check?.ok && (
                <span className="text-income">
                  {check.kind === "balance" ? t("importCard.balanceOk") : t("importCard.statementTotalOk")}
                </span>
              )}
              {check && !check.ok && (
                <span className="text-warning">
                  {t("review.checkOff", { amount: formatMoney(Math.abs(check.difference_minor)) })}
                </span>
              )}
            </div>
            {preview.review_reasons.length > 0 && (
              <ul className="mt-1 text-xs text-ink-muted list-disc pl-4">
                {preview.review_reasons.map((reason) => (
                  <li key={reason}>{t(`review.reason.${reason}` as MessageKey)}</li>
                ))}
              </ul>
            )}
          </div>
          <div className="flex items-center gap-4 shrink-0">
          {isPdf && onTeach && (
            <button
              type="button"
              aria-pressed={teach}
              onClick={() => {
                if (teach) cancelTeaching();
                else {
                  setTeach(true);
                  setFinished(false);
                  setStartTemplate(taught);
                  setAppliedHere(false);
                }
              }}
              className="text-sm text-accent-strong underline underline-offset-2"
            >
              {teach ? t("teach.cancel") : t("teach.start")}
            </button>
          )}
          <button
            ref={closeButton}
            type="button"
            onClick={onClose}
            className="text-sm text-ink-muted underline underline-offset-2 hover:text-ink"
          >
            {t("common.close")}
          </button>
          </div>
        </div>

        <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-2">
          <section aria-label={t("review.original")} className="min-h-0 flex flex-col border-r border-border bg-surface-sunken">
            {isPdf ? (
              <>
                <div className="flex items-center gap-2 px-3 py-2 border-b border-border text-xs text-ink-muted">
                  <button type="button" disabled={page <= 0} onClick={() => setPage(page - 1)} className="px-2 disabled:opacity-40" aria-label={t("review.prevPage")}>
                    ‹
                  </button>
                  <span>{t("tx.page", { page: page + 1, pages: preview.page_count })}</span>
                  <button
                    type="button"
                    disabled={page >= preview.page_count - 1}
                    onClick={() => setPage(page + 1)}
                    className="px-2 disabled:opacity-40"
                    aria-label={t("review.nextPage")}
                  >
                    ›
                  </button>
                  <span className="ml-auto" />
                  <button type="button" onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))} className="px-2" aria-label={t("review.zoomOut")}>
                    −
                  </button>
                  <button type="button" onClick={() => setZoom((z) => Math.min(3, z + 0.25))} className="px-2" aria-label={t("review.zoomIn")}>
                    +
                  </button>
                </div>
                <div ref={pageArea} className="flex-1 overflow-auto p-3">
                  <PdfPage
                    stagingId={preview.staging_id}
                    page={page}
                    zoom={zoom}
                    lines={preview.layout_lines.filter((line) => line.page === page)}
                    selected={teach ? picked?.index ?? null : selected}
                    onSelect={(index) => select(index, true)}
                    teach={teach ? { styleOf: teachStyle, onPick: setPicked } : undefined}
                  />
                </div>
                <Legend teach={teach} />
              </>
            ) : (
              <SourceRows rows={preview.source_rows} transactions={preview.transactions} selected={selected} onSelect={(i) => select(i, true)} />
            )}
          </section>

          <section aria-label={t("review.read")} className="min-h-0 overflow-auto">
            {finished && !teach && preview.detected_layout === "user_template" && !applying && (
              <div role="status" className="m-4 rounded-md bg-income/10 border border-income/30 px-3 py-2 text-xs text-income">
                {t("teach.done", { count: preview.transactions.length })}
              </div>
            )}
            {teach && onTeach && (
              <TeachReader
                picked={picked}
                example={example}
                roles={roles}
                template={template}
                applying={applying}
                hasTemplate={taught !== null || isUsable(template)}
                onUseAsExample={useAsExample}
                onRoles={changeRoles}
                onChange={changeTemplate}
                onDiscard={discardTemplate}
                onFinish={finishTeaching}
                result={{
                  active: preview.detected_layout === "user_template",
                  count: preview.transactions.length,
                  check: preview.total_check,
                }}
              />
            )}
            {preview.transactions.length === 0 ? (
              <p className="p-5 text-sm text-ink-muted">{t("review.nothingRead")}</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="text-ink-muted text-xs sticky top-0 bg-surface">
                  <tr className="border-b border-border">
                    <th className="text-left font-medium px-4 py-2">{t("col.date")}</th>
                    <th className="text-left font-medium px-4 py-2">{t("col.description")}</th>
                    <th className="text-right font-medium px-4 py-2">{t("col.amount")}</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.transactions.map((tx) => (
                    <tr
                      key={tx.source_row_index}
                      ref={(el) => {
                        if (el) rowRefs.current.set(tx.source_row_index, el);
                        else rowRefs.current.delete(tx.source_row_index);
                      }}
                      tabIndex={0}
                      aria-selected={selected === tx.source_row_index}
                      onClick={() => select(tx.source_row_index, false)}
                      onFocus={() => select(tx.source_row_index, false)}
                      onMouseEnter={() => select(tx.source_row_index, false)}
                      className={clsx(
                        "border-b border-border cursor-pointer outline-none",
                        selected === tx.source_row_index ? "bg-accent-soft" : "hover:bg-surface-sunken/60"
                      )}
                    >
                      <td className="px-4 py-1.5 whitespace-nowrap text-ink-muted">
                        {tx.parsed_date ? formatDate(tx.parsed_date) : <span className="text-warning">{tx.original_date_text ?? "—"}</span>}
                      </td>
                      <td className="px-4 py-1.5 text-ink">
                        {tx.original_description ?? "—"}
                        {tx.details && <span className="block text-xs text-ink-faint">{tx.details}</span>}
                      </td>
                      <td
                        className={clsx(
                          "px-4 py-1.5 text-right tabular-nums whitespace-nowrap",
                          tx.parsed_amount_minor === null ? "text-warning" : tx.parsed_amount_minor < 0 ? "text-expense" : "text-income"
                        )}
                      >
                        {tx.parsed_amount_minor === null
                          ? tx.original_amount_text ?? "—"
                          : formatSignedMoney(tx.parsed_amount_minor, tx.parsed_currency ?? "EUR")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-4 px-5 py-3 border-t border-border">
          <p className="mr-auto text-xs text-ink-muted max-w-xl">{t("review.howTo")}</p>
          {canImport && preview.account_id !== null && (
            <label className="flex items-center gap-2 text-xs text-ink">
              <input type="checkbox" checked={dontAskAgain} onChange={(e) => setDontAskAgain(e.target.checked)} />
              {t("review.dontAskAgain", { account: preview.account_name ?? "" })}
            </label>
          )}
          {preview.account_id === null && accountPicker}
          {canImport && (
            <Button variant="primary" disabled={importing} onClick={() => onImport(dontAskAgain)}>
              {importing ? t("importCard.importing") : t("review.confirmImport")}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

/** A PDF page as an image with a box on every line the reading used. */
function PdfPage({
  stagingId,
  page,
  zoom,
  lines,
  selected,
  onSelect,
  teach,
}: {
  stagingId: string;
  page: number;
  zoom: number;
  lines: LayoutLine[];
  selected: number | null;
  onSelect: (index: number) => void;
  /** teaching: every line can be picked, styled by what it was taught to be */
  teach?: { styleOf: (line: LayoutLine) => string; onPick: (line: LayoutLine) => void };
}) {
  const { t } = useI18n();
  // the image is rendered at `zoom` × PDF points: 1 point = zoom pixels
  // the boxes wait for the image they belong to (a new page or zoom loads anew)
  const src = stagedPageUrl(stagingId, page, zoom);
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const loaded = loadedSrc === src;
  const selectedRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selected, page]);

  return (
    <div className="relative inline-block shadow-sm bg-white">
      <img
        src={src}
        alt={t("review.pageImage", { page: page + 1 })}
        onLoad={() => setLoadedSrc(src)}
        className="block max-w-none"
      />
      {loaded &&
        lines
          .filter((line) => teach || line.role !== "text")
          .map((line) => {
            const active = line.index === selected;
            const style = teach ? teach.styleOf(line) : line.role;
            const clickable = teach !== undefined || line.role === "booking";
            return (
              <button
                key={line.index}
                ref={active ? selectedRef : undefined}
                type="button"
                title={t(`review.role.${style}` as MessageKey)}
                aria-label={`${t(`review.role.${style}` as MessageKey)}: ${line.text}`}
                onClick={() => (teach ? teach.onPick(line) : line.role === "booking" && onSelect(line.index))}
                className={clsx(
                  "absolute border rounded-sm",
                  ROLE_STYLE[style],
                  active && "ring-2 ring-accent-strong",
                  clickable ? "cursor-pointer" : "cursor-default"
                )}
                style={{
                  left: (line.x0 - 2) * zoom,
                  top: (line.y0 - 1.5) * zoom,
                  width: (line.x1 - line.x0 + 4) * zoom,
                  height: (line.y1 - line.y0 + 3) * zoom,
                }}
              />
            );
          })}
    </div>
  );
}

function Legend({ teach }: { teach: boolean }) {
  const { t } = useI18n();
  const roles = teach ? (["example", "booking", "ignored", "balance"] as const) : (["booking", "detail", "unreadable", "balance"] as const);
  return (
    <div className="flex flex-wrap gap-3 px-3 py-2 border-t border-border text-[11px] text-ink-muted">
      {roles.map((role) => (
        <span key={role} className="flex items-center gap-1">
          <span className={clsx("inline-block w-3 h-3 border rounded-sm", ROLE_STYLE[role])} />
          {t(`review.role.${role}` as MessageKey)}
        </span>
      ))}
    </div>
  );
}

/** A spreadsheet's rows, header first; rows that became bookings are marked. */
function SourceRows({
  rows,
  transactions,
  selected,
  onSelect,
}: {
  rows: string[][];
  transactions: ParsedTransactionPreview[];
  selected: number | null;
  onSelect: (index: number) => void;
}) {
  const byRow = new Map<number, number>();
  for (const tx of transactions) if (tx.location && "row" in tx.location) byRow.set(tx.location.row, tx.source_row_index);
  const selectedRef = useRef<HTMLTableRowElement>(null);
  useEffect(() => selectedRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }), [selected]);
  if (rows.length === 0) return null;
  return (
    <div className="flex-1 overflow-auto">
      <table className="text-xs bg-surface">
        <thead className="sticky top-0 bg-surface-sunken">
          <tr>
            {rows[0].map((cell, i) => (
              <th key={i} className="text-left font-semibold px-2 py-1 border-b border-border whitespace-nowrap">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(1).map((row, i) => {
            const index = byRow.get(i + 1);
            const active = index !== undefined && index === selected;
            return (
              <tr
                key={i}
                ref={active ? selectedRef : undefined}
                onClick={() => index !== undefined && onSelect(index)}
                className={clsx(
                  "border-b border-border",
                  index === undefined ? "text-ink-faint" : "cursor-pointer",
                  active && "bg-accent-soft"
                )}
              >
                {row.map((cell, j) => (
                  <td key={j} className="px-2 py-1 whitespace-nowrap max-w-[260px] truncate" title={cell}>
                    {cell}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
