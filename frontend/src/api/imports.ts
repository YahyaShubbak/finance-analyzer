import { apiDelete, apiGet, apiPost, apiUpload, apiUrl } from "./client";
import type {
  ImportCommitResult,
  ImportPreview,
  ImportRecord,
  ImportRemovalResult,
  ParseOptions,
  RowDecision,
} from "../types";

/** Without accountId the backend recognizes the account from the file when
 * it can (preview.account_recognized); otherwise preview.account_id is null. */
export function previewImport(file: File, accountId?: number) {
  return apiUpload<ImportPreview>("/api/imports/preview", file, accountId === undefined ? {} : { account_id: accountId });
}

/** Re-run the preview of an already uploaded file with different parse
 * options (column mapping, date format, ...) or another target account. */
/** accountId null: not chosen yet (e.g. while teaching the reader in the review). */
export function reparseImport(stagingId: string, accountId: number | null, options: ParseOptions) {
  return apiPost<ImportPreview>(`/api/imports/${stagingId}/reparse`, { account_id: accountId, options });
}

/** Read an uploaded file again as files of its kind are read now (after
 * another file of the kind was taught or confirmed). */
export function recognizeImport(stagingId: string) {
  return apiPost<ImportPreview>(`/api/imports/${stagingId}/recognize`);
}

/** The user dropped a previewed file without importing it. */
export function discardStagedImport(stagingId: string) {
  return apiDelete<void>(`/api/imports/staging/${stagingId}`);
}

/** `auto`: imported without the user looking at the preview — the backend
 * refuses if a row could meanwhile be a duplicate. */
export function commitImport(
  stagingId: string,
  accountId: number,
  rowDecisions: RowDecision[] = [],
  auto = false,
  verified = false
) {
  return apiPost<ImportCommitResult>("/api/imports/commit", {
    staging_id: stagingId,
    account_id: accountId,
    row_decisions: rowDecisions,
    auto,
    verified,
  });
}

/** A page of an uploaded PDF as an image (rendered by the backend). */
export function stagedPageUrl(stagingId: string, page: number, zoom: number) {
  return apiUrl(`/api/imports/staging/${stagingId}/pages/${page}?zoom=${zoom}`);
}

export function listImports() {
  return apiGet<ImportRecord[]>("/api/imports");
}

export function removeImports(importIds: number[]) {
  return apiPost<{ imports_removed: number; transactions_removed: number }>("/api/imports/remove", {
    import_ids: importIds,
  });
}

export function removeImport(importId: number) {
  return apiDelete<ImportRemovalResult>(`/api/imports/${importId}`);
}
