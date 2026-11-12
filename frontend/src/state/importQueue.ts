import { useSyncExternalStore } from "react";
import type { ImportCommitResult, ImportPreview, ImportRecord } from "../types";

/** What an import card has reached and what it is doing. Kept here, not in
 * the card: the card is unmounted while another page is shown, and the
 * answer to a request it sent (the upload, the import) must still arrive. */
export interface CardSnapshot {
  /** the request under way — one at a time */
  busy?: "waiting" | "reading" | "importing" | "undoing";
  /** why the last request failed (reading the file, undoing the import) */
  error?: string;
  /** why the import failed */
  commitError?: string;
  /** why the file was not imported by itself after all */
  autoRefused?: string;
  preview?: ImportPreview;
  committed?: ImportCommitResult;
  /** the list of imports has shown `committed` — from then on, its absence means it is gone */
  seenInHistory?: boolean;
  autoImported?: boolean;
  /** the user took over (chose an account, undid an import): no automatic import */
  manual?: boolean;
  /** the user chose the account: the file is not read again by itself */
  accountChosen?: boolean;
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

/** Returns the new cards' keys. */
export function addFiles(files: File[]): string[] {
  // A counter, not the file's name/size: dropping the same file twice
  // must still give each card its own identity.
  const added = files.map((file) => ({ key: `file-${nextKey++}`, file, snapshot: {} }));
  queue = [...queue, ...added];
  emit();
  return added.map((q) => q.key);
}

export function removeFile(key: string) {
  queue = queue.filter((q) => q.key !== key);
  if (reviewKey === key) reviewKey = null;
  emit();
}

// The import review fills the window: one file's at a time. Several files
// that want theirs looked at get it one after the other — opened together
// they lay on top of each other, and one Escape closed them all.
let reviewKey: string | null = null;

/** The file whose import review is open. */
export function useReviewKey(): string | null {
  return useSyncExternalStore(subscribe, () => reviewKey);
}

/** Opens a file's import review — unless another file's is open — or closes it. */
export function showReview(key: string, open: boolean) {
  if (open ? reviewKey !== null : reviewKey !== key) return;
  reviewKey = open ? key : null;
  emit();
}

/** Returns false when the file is not in the queue any more (its card was
 * removed, or everything was reset): the answer has nowhere to go. */
export function saveSnapshot(key: string, patch: CardSnapshot): boolean {
  if (!queue.some((q) => q.key === key)) return false;
  queue = queue.map((q) => (q.key === key ? { ...q, snapshot: { ...q.snapshot, ...patch } } : q));
  emit();
  return true;
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
  reviewKey = null;
  emit();
}

// Of many files dropped at once, only a few are uploaded and read at a time:
// each one is a full parse on the server (a PDF several times over), and all
// of them at once made every one slow — and the app with them.
export const MAX_PARALLEL_UPLOADS = 2;
let uploading = 0;
const waitingForSlot: Array<(release: () => void) => void> = [];

function grant(resolve: (release: () => void) => void) {
  uploading += 1;
  let released = false;
  resolve(() => {
    if (released) return;
    released = true;
    uploading -= 1;
    const next = waitingForSlot.shift();
    if (next) grant(next);
  });
}

/** Resolves when it is the caller's turn to upload, with the function that
 * ends the turn (to be called when the upload is over, however it ended). */
export function uploadSlot(): Promise<() => void> {
  return new Promise((resolve) => {
    if (uploading < MAX_PARALLEL_UPLOADS) grant(resolve);
    else waitingForSlot.push(resolve);
  });
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
