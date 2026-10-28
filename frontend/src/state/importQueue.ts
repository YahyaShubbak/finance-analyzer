import { useSyncExternalStore } from "react";
import type { ImportCommitResult, ImportPreview } from "../types";

/** What an import card has reached, so it is still there after visiting
 * another page (the card itself is unmounted meanwhile). */
export interface CardSnapshot {
  preview?: ImportPreview;
  committed?: ImportCommitResult;
  autoImported?: boolean;
  /** the user took over (chose an account, undid an import): no automatic import */
  manual?: boolean;
  undone?: boolean;
  /** the parse options come from the user's column/format dialog */
  formOptions?: boolean;
  /** the import review was closed — don't open it by itself again */
  reviewDismissed?: boolean;
}

export interface QueuedFile {
  key: string;
  file: File;
  snapshot: CardSnapshot;
}

let queue: QueuedFile[] = [];
let nextKey = 0;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useImportQueue(): QueuedFile[] {
  return useSyncExternalStore(subscribe, () => queue);
}

export function addFiles(files: File[]) {
  // A counter, not the file's name/size: dropping the same file twice
  // must still give each card its own identity.
  queue = [...queue, ...files.map((file) => ({ key: `file-${nextKey++}`, file, snapshot: {} }))];
  emit();
}

export function removeFile(key: string) {
  queue = queue.filter((q) => q.key !== key);
  emit();
}

export function saveSnapshot(key: string, patch: CardSnapshot) {
  queue = queue.map((q) => (q.key === key ? { ...q, snapshot: { ...q.snapshot, ...patch } } : q));
  emit();
}

/** Everything was reset: no card refers to the old data any more. */
export function clearQueue() {
  queue = [];
  emit();
}

// Counts what the user taught or confirmed by importing a file by hand. Files
// dropped together were all read on upload — before that — and read
// themselves again when it changes (ImportFileCard).
let learned = 0;

export function noteLearned() {
  learned += 1;
  emit();
}

export function useLearnedVersion(): number {
  return useSyncExternalStore(subscribe, () => learned);
}
