import "@testing-library/jest-dom/vitest";

// Unit tests run without a backend. The opt-in integration test
// (src/test/app.integration.test.tsx) talks to a throwaway backend given via
// E2E_API_BASE — never to the database you actually use.

// Node >= 25 ships an experimental global `localStorage` that shadows
// jsdom's and is undefined unless Node is started with --localstorage-file.
// Provide a spec-compatible in-memory Storage in that case.
if (typeof window !== "undefined" && !window.localStorage) {
  const store = new Map<string, string>();
  const memoryStorage: Storage = {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key) => (store.has(key) ? store.get(key)! : null),
    key: (index) => [...store.keys()][index] ?? null,
    removeItem: (key) => void store.delete(key),
    setItem: (key, value) => void store.set(key, String(value)),
  };
  Object.defineProperty(globalThis, "localStorage", { value: memoryStorage, configurable: true });
  Object.defineProperty(window, "localStorage", { value: memoryStorage, configurable: true });
}

// The UI defaults to German; tests assert the English texts. Set before any
// test module imports src/i18n/core.ts, which reads the stored choice.
localStorage.setItem("finance.lang", "en");
