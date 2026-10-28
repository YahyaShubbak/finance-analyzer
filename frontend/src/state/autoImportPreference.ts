// Whether a file whose account is recognized and whose preview shows
// nothing to check is imported right away (Imports page). On by default.
const STORAGE_KEY = "finance.autoImport";

export function loadAutoImportPreference(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== "false";
  } catch {
    return true;
  }
}

export function saveAutoImportPreference(value: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, String(value));
  } catch {
    // not remembered in private mode
  }
}
