// What the user answered to the reminder of new statements (AppShell):
// "Later" hides it until the app is opened again (sessionStorage), "OK"
// until a newer statement is due (the reminders seen are remembered),
// "Don't remind me" for good — Settings turns it back on.
import type { StatementReminder } from "../types";

const STORAGE_KEY = "finance.statementReminders";
const SESSION_KEY = "finance.statementReminders.later";

interface Stored {
  off?: boolean;
  seen?: string[];
}

export const reminderKey = (r: StatementReminder) => `${r.account_id}:${r.period_end}`;

function load(): Stored {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as Stored;
  } catch {
    return {};
  }
}

function save(value: Stored) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // not remembered in private mode
  }
}

export function statementRemindersEnabled(): boolean {
  return !load().off;
}

export function setStatementRemindersEnabled(enabled: boolean) {
  save({ ...load(), off: !enabled });
}

/** The reminders still to show: none after "Later" in this session, and
 * none of those already answered with "OK". */
export function remindersToShow(reminders: StatementReminder[]): StatementReminder[] {
  const stored = load();
  let later = false;
  try {
    later = sessionStorage.getItem(SESSION_KEY) === "true";
  } catch {
    // shown again then
  }
  if (stored.off || later) return [];
  const seen = new Set(stored.seen ?? []);
  return reminders.filter((r) => !seen.has(reminderKey(r)));
}

export function remindLater() {
  try {
    sessionStorage.setItem(SESSION_KEY, "true");
  } catch {
    // shown again on the next page load then
  }
}

/** Only the current reminders are kept: an older one never comes back. */
export function markRemindersSeen(reminders: StatementReminder[]) {
  save({ ...load(), seen: reminders.map(reminderKey) });
}
