import { useState } from "react";
import { Card } from "../ui";
import { useI18n } from "../../i18n/useI18n";
import { setStatementRemindersEnabled, statementRemindersEnabled } from "../../state/statementReminderPreference";

export function StatementReminderSection() {
  const { t } = useI18n();
  const [enabled, setEnabled] = useState(statementRemindersEnabled);

  return (
    <Card className="p-5">
      <h2 className="text-sm font-semibold text-ink">{t("settings.reminders")}</h2>
      <p className="text-xs text-ink-muted mt-1 max-w-lg">{t("settings.remindersHint")}</p>
      <label className="mt-3 flex items-center gap-2 text-sm text-ink">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => {
            setStatementRemindersEnabled(e.target.checked);
            setEnabled(e.target.checked);
          }}
        />
        {t("settings.remindersOn")}
      </label>
    </Card>
  );
}
