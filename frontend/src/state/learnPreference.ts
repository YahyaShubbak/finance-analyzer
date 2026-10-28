// Whether a category chosen by hand is also learned for similar
// transactions (Transactions page and review queue). On by default.
const STORAGE_KEY = "finance.learnCategories";

export function loadLearnPreference(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== "false";
  } catch {
    return true;
  }
}

export function saveLearnPreference(value: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, String(value));
  } catch {
    // not remembered in private mode
  }
}
