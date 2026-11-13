import { apiDelete, apiGet, apiPost, apiPostForm, apiUpload, apiUrl } from "./client";
import type { BackupInfo, RestoreResult } from "../types";

export function listBackups() {
  return apiGet<BackupInfo[]>("/api/backup");
}

export function createBackup() {
  return apiPost<BackupInfo>("/api/backup/create");
}

export function deleteBackup(filename: string) {
  return apiDelete<void>(`/api/backup/${encodeURIComponent(filename)}`);
}

export function backupDownloadUrl(filename: string) {
  return apiUrl(`/api/backup/${encodeURIComponent(filename)}/download`);
}

export function restoreFromUpload(file: File) {
  return apiUpload<RestoreResult>("/api/backup/restore", file, { confirm: "true" });
}

export function restoreFromExisting(filename: string) {
  return apiPostForm<RestoreResult>(`/api/backup/${encodeURIComponent(filename)}/restore`, { confirm: "true" });
}
