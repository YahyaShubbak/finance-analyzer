import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// The real hooks and API functions; only the requests themselves are stubbed.
vi.mock("../api/client", async (original) => ({
  ...(await original<typeof import("../api/client")>()),
  apiGet: vi.fn(),
}));

const FILTERS_KEY = "finance.filters.v1";
const storedCategory = () => JSON.parse(localStorage.getItem(FILTERS_KEY) ?? "{}").category;

/** The page as after a reload: the filter store reads the stored filters
 * when it is first loaded. Returns how to answer the categories request. */
async function openPageWithStoredCategory(category: string) {
  vi.resetModules();
  localStorage.setItem(FILTERS_KEY, JSON.stringify({ category }));
  const { apiGet } = await import("../api/client");
  let answerCategories: (categories: unknown[]) => void = () => {};
  vi.mocked(apiGet).mockImplementation((path: string) => {
    if (path === "/api/accounts") return Promise.resolve([]) as never;
    if (path === "/api/transactions") return Promise.resolve({ items: [], total: 0, page: 1, page_size: 25 }) as never;
    if (path === "/api/categories") return new Promise((resolve) => (answerCategories = resolve)) as never;
    return Promise.reject(new Error(`not part of this test: ${path}`)) as never;
  });
  const { Transactions } = await import("./Transactions");
  const { LanguageProvider } = await import("../i18n/LanguageProvider");
  render(
    <LanguageProvider>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <Transactions />
        </MemoryRouter>
      </QueryClientProvider>
    </LanguageProvider>
  );
  await waitFor(() => expect(apiGet).toHaveBeenCalledWith("/api/categories"));
  await waitFor(() => expect(apiGet).toHaveBeenCalledWith("/api/transactions", expect.anything()));
  return (categories: unknown[]) => act(async () => answerCategories(categories));
}

const BUILT_IN = { name: "Groceries", built_in: true, id: null, transaction_count: 0 };

describe("Transactions: a remembered filter on one of the user's own categories", () => {
  beforeEach(() => localStorage.removeItem(FILTERS_KEY));

  it("survives a reload — also while the categories are still being loaded", async () => {
    const answerCategories = await openPageWithStoredCategory("Darlehen");
    expect(storedCategory()).toBe("Darlehen"); // the built-in names alone don't make it stale

    await answerCategories([BUILT_IN, { name: "Darlehen", built_in: false, id: 1, transaction_count: 4 }]);
    expect(storedCategory()).toBe("Darlehen");
  });

  it("is dropped once the loaded categories show it is gone", async () => {
    const answerCategories = await openPageWithStoredCategory("Darlehen");

    await answerCategories([BUILT_IN]);
    await waitFor(() => expect(storedCategory()).toBeUndefined());
  });
});
