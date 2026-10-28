import { Button } from "../ui";
import { datePresets, type DatePreset, type DateRange } from "../../lib/datePresets";
import { useI18n } from "../../i18n/useI18n";

export type { DateRange } from "../../lib/datePresets";

export function DateRangeSelector({
  range,
  onChange,
}: {
  range: DateRange;
  onChange: (range: DateRange) => void;
}) {
  const { t } = useI18n();
  const presets = datePresets();

  return (
    <div className="flex flex-wrap items-center gap-2.5">
      {(Object.entries(presets) as [DatePreset, DateRange][]).map(([preset, value]) => {
        const isActive = value.start === range.start && value.end === range.end;
        return (
          <Button
            key={preset}
            variant={isActive ? "primary" : "secondary"}
            className="!px-2.5 !py-1.5 text-xs"
            onClick={() => onChange(value)}
          >
            {t(`preset.${preset}`)}
          </Button>
        );
      })}
      <span className="text-ink-faint text-xs mx-1">{t("range.custom")}</span>
      <input
        type="date"
        className="text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink"
        aria-label={t("tx.from")}
        value={range.start ?? ""}
        onChange={(e) => onChange({ ...range, start: e.target.value || undefined })}
      />
      <span className="text-ink-faint text-sm">–</span>
      <input
        type="date"
        className="text-sm border border-border-strong rounded-md px-2.5 py-1.5 bg-surface text-ink"
        aria-label={t("tx.to")}
        value={range.end ?? ""}
        onChange={(e) => onChange({ ...range, end: e.target.value || undefined })}
      />
      {range.start && range.end && range.start > range.end && (
        <span role="alert" className="text-xs text-warning">{t("range.reversed")}</span>
      )}
    </div>
  );
}
