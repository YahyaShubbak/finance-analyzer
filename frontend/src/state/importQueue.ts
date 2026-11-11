import { useSyncExternalStore } from "react";
import type { ImportCommitResult, ImportPreview, ImportRecord } from "../types";

/** What an import card has reached, so it is still there after visiting
 * another page (the card itself is unmounted meanwhile). */
export interface CardSnapshot {
  preview?: ImportPreview;
  committed?: ImportCommitResult;
  /** the list of imports has shown `committed` — from then on, its absence means it is gone */
  seenInHistory?: boolean;
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

/** Is the import a card made still in the list of imports? A card outlives
 * its import: the import may be removed in the list (or in another window),
 * and a restored backup brings other imports with it. Its number alone
 * doesn't tell — a later import can get the number of a removed one — so the
 * file name must be the card's too. "Undo" asks the server to remove the
 * import with that number, so it is only offered while this holds. */
export function isSameImport(committed: ImportCommitResult, imports: ImportRecord[] | undefined): boolean {
  return Boolean(imports?.some((r) => r.id === committed.import_id && r.filename === committed.filename));
}

/** Everything was reset or replaced (a restored backup): no card refers to
 * the data there is now. */
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
