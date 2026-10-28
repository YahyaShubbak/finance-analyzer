import { apiGet, apiPost } from "./client";
import type { SystemInfo } from "../types";

export function getSystemInfo() {
  return apiGet<SystemInfo>("/api/system/info");
}

/** Delete all data (bookings, imports with their originals, accounts, own
 * categories and rules, budgets, points, exports); backups only when asked. */
export function resetEverything(deleteBackups: boolean) {
  return apiPost<{ rows_deleted: number; files_deleted: number }>("/api/system/reset", {
    confirm: "RESET",
    delete_backups: deleteBackups,
  });
}
