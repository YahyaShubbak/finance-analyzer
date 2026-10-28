import { useId } from "react";
import clsx from "clsx";
import { useI18n } from "../../i18n/useI18n";
import type { MessageKey } from "../../i18n/core";
import type { LayoutLine, PdfTemplate, TemplateColumn, TemplateLabel, TotalCheck } from "../../types";
import { isUsable, looksLikeDate, type WordRole } from "../../lib/pdfTemplate";
import { formatMoney } from "../../lib/format";
import { Button } from "../ui";

const ROLES: TemplateColumn[] = ["date", "value_date", "text", "amount", "sign"];
const LABELS: TemplateLabel[] = ["total", "opening", "closing"];

const WORD_ROLE_STYLE: Record<TemplateColumn, string> = {
  date: "border-accent bg-accent-soft text-accent-strong",
  value_date: "border-accent/50 bg-accent-soft/60 text-accent-strong",
  text: "border-border bg-surface text-ink",
  amount: "border-income bg-income/15 text-income",
  sign: "border-warning bg-warning/20 text-warning",
};

/**
 * Teaching the reader a layout it doesn't understand: the user clicks a line
 * of the original and says what it is — an example booking (whose words get
 * roles: date, text, amount, …), a line to skip, or the line with the
 * statement total or a balance — and how unsigned amounts are meant. Every
 * change is read again at once; what was taught is kept for the next files
 * of this kind.
 */
export function TeachReader({
  picked,
  example,
  roles,
  template,
  applying,
  hasTemplate,
  onUseAsExample,
  onRoles,
  onChange,
  onDiscard,
  onFinish,
  result,
}: {
  picked: LayoutLine | null;
  example: LayoutLine | null;
  roles: WordRole[];
  template: PdfTemplate;
  applying: boolean;
  /** the file is read with a taught template (now or from an earlier file) */
  hasTemplate: boolean;
  onUseAsExample: (line: LayoutLine) => void;
  onRoles: (roles: WordRole[]) => void;
  onChange: (template: PdfTemplate) => void;
  onDiscard: () => void;
  onFinish: () => void;
  /** the file as read now: with the taught template (active) or the built-in readers */
  result: { active: boolean; count: number; check: TotalCheck | null };
}) {
  const { t } = useI18n();
  const id = useId();
  const ignored = new Set(template.ignore);

  function toggleIgnore(text: string) {
    onChange({
      ...template,
      ignore: ignored.has(text) ? template.ignore.filter((x) => x !== text) : [...template.ignore, text],
    });
  }

  function setLabel(kind: TemplateLabel, text: string | null) {
    const labels = { ...template.labels };
    if (text === null) delete labels[kind];
    else labels[kind] = text;
    onChange({ ...template, labels });
  }

  const missingDate = example !== null && !template.columns.date;
  const missingAmount = example !== null && !template.columns.amount;
  const lineHasNoDate = example !== null && !example.words.some((w) => looksLikeDate(w.text));
  return (
    <div className="border-b border-border bg-accent-soft/30 px-4 py-3 space-y-3 text-xs">
      <div className="flex items-start justify-between gap-3">
        <p className="text-ink-muted max-w-xl">{t("teach.intro")}</p>
        <span role="status" className="shrink-0 text-ink-muted">
          {applying ? t("teach.applying") : null}
        </span>
      </div>

      {picked ? (
        <div className="rounded-md border border-border bg-surface p-2 space-y-2">
          <div className="font-mono text-[11px] text-ink break-all">{picked.text}</div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-ink-muted">{t("teach.thisLineIs")}</span>
            <ActionButton active={example?.index === picked.index} onClick={() => onUseAsExample(picked)}>
              {t("teach.asExample")}
            </ActionButton>
            <ActionButton active={ignored.has(picked.text)} onClick={() => toggleIgnore(picked.text)}>
              {t("teach.asIgnored")}
            </ActionButton>
            {LABELS.map((kind) => (
              <ActionButton
                key={kind}
                active={template.labels[kind] === picked.text}
                onClick={() => setLabel(kind, template.labels[kind] === picked.text ? null : picked.text)}
              >
                {t(`teach.as.${kind}` as MessageKey)}
              </ActionButton>
            ))}
          </div>
        </div>
      ) : (
        <p className="text-ink">{hasTemplate && !example ? t("teach.pickToChange") : t("teach.pickLine")}</p>
      )}

      {example && (
        <fieldset className="space-y-1.5">
          <legend className="font-medium text-ink mb-1">{t("teach.exampleWords")}</legend>
          <div className="flex flex-wrap gap-1.5">
            {example.words.map((word, i) => {
              const role = roles[i] ?? null;
              return (
                <label
                  key={i}
                  className={clsx(
                    "flex flex-col items-stretch gap-0.5 rounded border px-1.5 py-1",
                    role ? WORD_ROLE_STYLE[role] : "border-dashed border-border text-ink-faint"
                  )}
                >
                  <span className="font-mono text-[11px] whitespace-nowrap">{word.text}</span>
                  <select
                    value={role ?? ""}
                    aria-label={t("teach.wordRole", { word: word.text })}
                    onChange={(e) => {
                      const next = [...roles];
                      next[i] = (e.target.value || null) as WordRole;
                      onRoles(next);
                    }}
                    className="text-[11px] bg-transparent"
                  >
                    <option value="">{t("teach.role.none")}</option>
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {t(`teach.role.${r}` as MessageKey)}
                      </option>
                    ))}
                  </select>
                </label>
              );
            })}
          </div>
          {lineHasNoDate ? (
            <p className="text-warning">{t("teach.noDateInLine")}</p>
          ) : (
            (missingDate || missingAmount) && (
              <p className="text-warning">
                {missingDate && missingAmount
                  ? t("teach.needDateAndAmount")
                  : missingDate
                    ? t("teach.needDate")
                    : t("teach.needAmount")}
              </p>
            )
          )}
        </fieldset>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <fieldset className="space-y-1">
          <legend className="font-medium text-ink mb-1">{t("teach.signRule")}</legend>
          {(["unsigned_is_expense", "unsigned_is_income", "as_printed"] as const).map((rule) => (
            <label key={rule} className="flex items-center gap-2 text-ink">
              <input
                type="radio"
                name={`${id}-sign`}
                checked={template.sign_rule === rule}
                onChange={() => onChange({ ...template, sign_rule: rule })}
              />
              {t(`teach.sign.${rule}` as MessageKey)}
            </label>
          ))}
          <p className="text-ink-faint">{t("teach.signHint")}</p>
        </fieldset>
        <fieldset className="space-y-1">
          <legend className="font-medium text-ink mb-1">{t("teach.documentType")}</legend>
          {(["bank_statement", "credit_card_statement"] as const).map((kind) => (
            <label key={kind} className="flex items-center gap-2 text-ink">
              <input
                type="radio"
                name={`${id}-kind`}
                checked={template.document_type === kind}
                onChange={() => onChange({ ...template, document_type: kind })}
              />
              {kind === "bank_statement" ? t("imports.docType.bank") : t("imports.docType.cardStatement")}
            </label>
          ))}
        </fieldset>
      </div>

      {(template.ignore.length > 0 || Object.keys(template.labels).length > 0) && (
        <ul className="space-y-1">
          {template.ignore.map((text) => (
            <TaughtLine key={`i-${text}`} label={t("teach.ignoredLine")} text={text} onRemove={() => toggleIgnore(text)} />
          ))}
          {LABELS.filter((kind) => template.labels[kind]).map((kind) => (
            <TaughtLine
              key={`l-${kind}`}
              label={t(`teach.as.${kind}` as MessageKey)}
              text={template.labels[kind]!}
              onRemove={() => setLabel(kind, null)}
            />
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-3 border-t border-border pt-3">
        <span role="status" className="mr-auto">
          {applying ? (
            <span className="text-ink-muted">{t("teach.applying")}</span>
          ) : result.active ? (
            <>
              <span className="text-ink">{t("teach.result", { count: result.count })}</span>
              {result.check?.ok && <span className="text-income"> · ✓ {t("teach.checkOk")}</span>}
              {result.check && !result.check.ok && (
                <span className="text-warning">
                  {" "}
                  · {t("teach.checkOff", { amount: formatMoney(Math.abs(result.check.difference_minor)) })}
                </span>
              )}
            </>
          ) : (
            <span className="text-ink-muted">{t("teach.notYet")}</span>
          )}
        </span>
        {hasTemplate && (
          <button type="button" className="text-ink-muted underline underline-offset-2 hover:text-ink" onClick={onDiscard}>
            {t("teach.discard")}
          </button>
        )}
        <Button variant="primary" className="!py-1 text-xs" disabled={applying || !isUsable(template)} onClick={onFinish}>
          {t("teach.finish")}
        </Button>
      </div>
    </div>
  );
}

function ActionButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={clsx(
        "rounded border px-2 py-0.5",
        active ? "border-accent bg-accent text-white" : "border-border bg-surface text-ink hover:border-accent"
      )}
    >
      {children}
    </button>
  );
}

function TaughtLine({ label, text, onRemove }: { label: string; text: string; onRemove: () => void }) {
  const { t } = useI18n();
  return (
    <li className="flex items-center gap-2">
      <span className="text-ink-muted shrink-0">{label}:</span>
      <span className="font-mono text-[11px] text-ink truncate">{text}</span>
      <button type="button" className="text-ink-muted hover:text-danger" aria-label={t("teach.undoLine", { text })} onClick={onRemove}>
        ×
      </button>
    </li>
  );
}
