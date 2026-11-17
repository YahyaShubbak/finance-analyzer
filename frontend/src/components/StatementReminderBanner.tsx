import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listStatementReminders } from "../api/accounts";
import { Button } from "./ui";
import { useI18n } from "../i18n/useI18n";
import { formatDate } from "../lib/format";
import {
  markRemindersSeen,
  remindLater,
  setStatementRemindersEnabled,
  remindersToShow,
  statementRemindersEnabled,
} from "../state/statementReminderPreference";
import type { StatementReminder } from "../types";

/** On opening the app: which newer statements could be imported now. */
export function StatementReminderBanner() {
  const { t } = useI18n();
  const [closed, setClosed] = useState(false);
  const { data } = useQuery({
    queryKey: ["statement-reminders"],
    queryFn: listStatementReminders,
    enabled: statementRemindersEnabled(),
    staleTime: Infinity,
  });
  const shown = closed || !data ? [] : remindersToShow(data);
  if (shown.length === 0) return null;

  const rhythm = (r: StatementReminder) =>
    r.rhythm_months === 1
      ? r.month_end ? t("reminder.monthlyEnd") : t("reminder.monthlyDay", { day: r.day })
      : r.month_end
        ? t("reminder.everyMonthsEnd", { months: r.rhythm_months })
        : t("reminder.everyMonthsDay", { months: r.rhythm_months, day: r.day });
  const close = (answer: () => void) => {
    answer();
    setClosed(true);
  };

  return (
    <div role="status" className="px-8 py-3 text-sm bg-accent-soft border-b border-accent/20">
      <p className="font-medium text-accent-strong">{t("reminder.title")}</p>
      <ul className="mt-1 space-y-0.5 text-ink">
        {shown.map((r) => (
          <li key={r.account_id}>
            <span className="font-medium">{r.account_name}</span>
            {" — "}
            {r.missing > 1
              ? t("reminder.statements", { count: r.missing, date: formatDate(r.period_end) })
              : t("reminder.statement", { date: formatDate(r.period_end) })}
            <span className="text-ink-muted"> ({rhythm(r)})</span>
          </li>
        ))}
      </ul>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Link to="/imports" className="text-accent-strong underline mr-2" onClick={() => setClosed(true)}>
          {t("reminder.toImports")}
        </Link>
        <Button variant="secondary" title={t("reminder.laterHint")} onClick={() => close(remindLater)}>
          {t("reminder.later")}
        </Button>
        <Button variant="secondary" title={t("reminder.okHint")} onClick={() => close(() => markRemindersSeen(data ?? []))}>
          {t("reminder.ok")}
        </Button>
        <Button variant="ghost" title={t("reminder.neverHint")} onClick={() => close(() => setStatementRemindersEnabled(false))}>
          {t("reminder.never")}
        </Button>
      </div>
    </div>
  );
}
