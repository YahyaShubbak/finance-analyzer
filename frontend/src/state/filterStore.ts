import { useCallback, useEffect, useState } from "react";
import type { TransactionType } from "../types";

const STORAGE_KEY = "finance.filters.v1";

export interface PersistedFilters {
  accountId: number | undefined;
  category: string | undefined;
  transactionType: TransactionType | undefined;
  start: string | undefined;
  end: string | undefined;
  search: string | undefined;
}

const DEFAULT_FILTERS: PersistedFilters = {
  accountId: undefined,
  category: undefined,
  transactionType: undefined,
  start: undefined,
  end: undefined,
  search: undefined,
};

function loadFilters(): PersistedFilters {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_FILTERS;
    return { ...DEFAULT_FILTERS, ...JSON.parse(raw) };
  } catch {
    return DEFAULT_FILTERS;
  }
}

// Simple shared-state hook: several components can read/update the same
// persisted filters within one page without prop-drilling. Data itself is
// still always re-fetched from the API — this only remembers the user's
// last chosen filter values across reloads.
let listeners: Array<(f: PersistedFilters) => void> = [];
let current: PersistedFilters = loadFilters();

function setFilters(update: Partial<PersistedFilters>) {
  current = { ...current, ...update };
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(current));
  } catch {
    // localStorage unavailable (e.g. private browsing) — filters just won't persist
  }
  listeners.forEach((l) => l(current));
}

/** Forget every filter — also the copy this module keeps while the app is
 * open: removing the stored one alone is undone by the next change, which
 * writes that copy back. */
export function resetFilters() {
  setFilters(DEFAULT_FILTERS);
}

export function useFilters(): [PersistedFilters, (update: Partial<PersistedFilters>) => void, () => void] {
  const [filters, setLocal] = useState(current);

  useEffect(() => {
    listeners.push(setLocal);
    return () => {
      listeners = listeners.filter((l) => l !== setLocal);
    };
  }, []);

  const update = useCallback((patch: Partial<PersistedFilters>) => setFilters(patch), []);
  const reset = useCallback(() => resetFilters(), []);

  return [filters, update, reset];
}
