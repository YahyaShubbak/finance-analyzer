import { useCallback, useState } from "react";
import { datePresets, matchingPreset, type DatePreset, type DateRange } from "../lib/datePresets";

const STORAGE_KEY = "finance.dashboard.v1";

interface StoredPeriod {
  preset?: DatePreset;
  start?: string;
  end?: string;
  accountId?: number;
}

function load(): StoredPeriod {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as StoredPeriod;
  } catch {
    return {};
  }
}

function save(value: StoredPeriod) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // localStorage unavailable (e.g. private browsing) — just won't persist
  }
}

/** The Dashboard's own, visible period + account selection — independent
 * of the Transactions page filters. A preset is stored by NAME so that
 * "This month" still means this month tomorrow. Default: this month, all
 * accounts. */
export function useDashboardPeriod(): {
  range: DateRange;
  accountId: number | undefined;
  setRange: (range: DateRange) => void;
  setAccountId: (id: number | undefined) => void;
} {
  const [stored, setStored] = useState<StoredPeriod>(() => {
    const value = load();
    return value.preset || value.start || value.end ? value : { ...value, preset: "This month" };
  });

  const range: DateRange = stored.preset ? datePresets()[stored.preset] : { start: stored.start, end: stored.end };

  const update = useCallback((patch: StoredPeriod) => {
    setStored((prev) => {
      const next = { ...prev, ...patch };
      save(next);
      return next;
    });
  }, []);

  const setRange = useCallback(
    (next: DateRange) => {
      const preset = matchingPreset(next);
      update(preset ? { preset, start: undefined, end: undefined } : { preset: undefined, ...next });
    },
    [update]
  );
  const setAccountId = useCallback((id: number | undefined) => update({ accountId: id }), [update]);

  return { range, accountId: stored.accountId, setRange, setAccountId };
}
