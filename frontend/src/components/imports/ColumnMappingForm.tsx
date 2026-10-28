import { useState } from "react";
import { Button } from "../ui";
import { describeDateFormat } from "../../lib/format";
import type { ImportPreview, MappableField, ParseOptions } from "../../types";
import type { MessageKey } from "../../i18n/core";
import { useI18n } from "../../i18n/useI18n";

// Same formats the backend accepts (backend/app/importers/parsing_utils.py DATE_FORMATS).
const DATE_FORMATS = [
  "%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d/%m/%y", "%m/%d/%y",
  "%d-%m-%Y", "%Y/%m/%d", "%Y.%m.%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%d-%b-%Y", "%Y%m%d",
];

const FIELDS: { field: MappableField; label: MessageKey; hint?: MessageKey }[] = [
  { field: "date", label: "mapping.field.date", hint: "mapping.hint.required" },
  { field: "description", label: "mapping.field.description" },
  { field: "counterparty", label: "mapping.field.counterparty", hint: "mapping.hint.counterparty" },
  { field: "amount", label: "mapping.field.amount", hint: "mapping.hint.amount" },
  { field: "debit", label: "mapping.field.debit", hint: "mapping.hint.insteadOfAmount" },
  { field: "credit", label: "mapping.field.credit", hint: "mapping.hint.insteadOfAmount" },
  { field: "currency", label: "mapping.field.currency" },
];

const selectClass = "text-sm border border-border-strong rounded-md px-2 py-1.5 bg-surface text-ink w-full";

export function ColumnMappingForm({
  preview,
  isPending,
  onSubmit,
  onCancel,
}: {
  preview: ImportPreview;
  isPending: boolean;
  onSubmit: (options: ParseOptions) => void;
  onCancel?: () => void;
}) {
  const { t } = useI18n();
  const [headerRow, setHeaderRow] = useState<number>((preview.header_row_index ?? 0) + 1);
  const [mapping, setMapping] = useState<Partial<Record<MappableField, string | null>>>(() => {
    const initial: Partial<Record<MappableField, string | null>> = {};
    for (const { field } of FIELDS) {
      initial[field] = preview.options.column_mapping?.[field] ?? preview.detected_columns[field] ?? null;
    }
    return initial;
  });
  const [dateFormat, setDateFormat] = useState<string>(preview.options.date_format ?? "");
  const [decimalSeparator, setDecimalSeparator] = useState<string>(preview.options.decimal_separator ?? "");
  const [invertSigns, setInvertSigns] = useState<boolean>(Boolean(preview.options.invert_signs));

  const headerRowChanged = headerRow - 1 !== preview.header_row_index;
  const hasAmount = Boolean(mapping.amount || mapping.debit || mapping.credit);
  const hasText = Boolean(mapping.description || mapping.counterparty);
  const canSubmit = headerRowChanged || (Boolean(mapping.date) && hasAmount && hasText);
  const dateChoices = preview.date_format_candidates.length > 1 ? preview.date_format_candidates : DATE_FORMATS;

  function submit() {
    onSubmit({
      // A different header row means different column names: let the
      // backend detect the columns of the new header first.
      column_mapping: headerRowChanged ? null : mapping,
      header_row: headerRow - 1,
      date_format: dateFormat || null,
      decimal_separator: (decimalSeparator || null) as ParseOptions["decimal_separator"],
      // unticking after the app inverted the amounts is an explicit "no";
      // never touched stays automatic (null)
      invert_signs: invertSigns ? true : preview.options.invert_signs == null ? null : false,
    });
  }

  return (
    <div className="rounded-md border border-border bg-surface-sunken/50 p-3 space-y-3">
      <div className="text-xs text-ink-muted">
        {t("mapping.intro")}
      </div>

      <label className="flex items-center gap-2 text-xs text-ink">
        {t("mapping.headerRow")}
        <input
          type="number"
          min={1}
          value={headerRow}
          onChange={(e) => setHeaderRow(Math.max(1, Number(e.target.value) || 1))}
          className="w-20 text-sm border border-border-strong rounded-md px-2 py-1 bg-surface"
        />
        <span className="text-ink-faint">{t("mapping.headerRowHint")}</span>
      </label>

      {!headerRowChanged && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2">
          {FIELDS.map(({ field, label, hint }) => (
            <label key={field} className="text-xs text-ink space-y-1">
              <span>
                {t(label)} {hint && <span className="text-ink-faint">({t(hint)})</span>}
              </span>
              <select
                className={selectClass}
                value={mapping[field] ?? ""}
                onChange={(e) => setMapping((prev) => ({ ...prev, [field]: e.target.value || null }))}
              >
                <option value="">{t("common.none")}</option>
                {preview.available_columns.map((col) => (
                  <option key={col} value={col}>
                    {col}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2">
        <label className="text-xs text-ink space-y-1">
          <span>
            {t("mapping.dateFormat")}{" "}
            {preview.date_format_candidates.length > 1 && <span className="text-warning">{t("mapping.pleaseChoose")}</span>}
          </span>
          <select className={selectClass} value={dateFormat} onChange={(e) => setDateFormat(e.target.value)}>
            <option value="">{t("mapping.detect")}</option>
            {dateChoices.map((fmt) => (
              <option key={fmt} value={fmt}>
                {describeDateFormat(fmt, t)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-ink space-y-1">
          <span>
            {t("mapping.decimal")}{" "}
            {preview.needs_decimal_separator && <span className="text-warning">{t("mapping.pleaseChoose")}</span>}
          </span>
          <select className={selectClass} value={decimalSeparator} onChange={(e) => setDecimalSeparator(e.target.value)}>
            <option value="">{t("mapping.detect")}</option>
            <option value=",">{t("mapping.comma")}</option>
            <option value=".">{t("mapping.point")}</option>
          </select>
        </label>
      </div>

      <label className="flex items-start gap-2 text-xs text-ink">
        <input type="checkbox" className="mt-0.5" checked={invertSigns} onChange={(e) => setInvertSigns(e.target.checked)} />
        <span>
          {t("mapping.invert")} <span className="text-ink-faint">{t("mapping.invertHint")}</span>
        </span>
      </label>

      <div className="flex gap-2">
        <Button variant="primary" disabled={!canSubmit || isPending} onClick={submit}>
          {isPending ? t("mapping.updating") : t("common.apply")}
        </Button>
        {onCancel && (
          <Button variant="ghost" onClick={onCancel} disabled={isPending}>
            {t("common.cancel")}
          </Button>
        )}
      </div>
    </div>
  );
}
