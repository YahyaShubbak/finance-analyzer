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

const BOOKING = {
  id: 1, account_id: 1, account_name: "Giro", transaction_date: "2026-03-01", normalized_description: "Shop",
  merchant: "Shop", category: "Groceries", amount_minor: -1000, currency: "EUR", transaction_type: "expense",
  is_duplicate: false, is_transfer: false, needs_review: false, review_reason: null, notes: null,
};

describe("Transactions: paging", () => {
  beforeEach(() => {
    localStorage.removeItem(FILTERS_KEY);
  });

  it("shows the last page that exists when the list got shorter", async () => {
    vi.resetModules();
    const { apiGet } = await import("../api/client");
    // 30 bookings (two pages) — but by the time page 2 is asked for, only 20 are left
    vi.mocked(apiGet).mockImplementation((path: string, params?: Record<string, unknown>) => {
      if (path === "/api/transactions") {
        const shrunk = vi.mocked(apiGet).mock.calls.some(([p, q]) => p === path && (q as { page?: number })?.page === 2);
        return Promise.resolve(
          params?.page === 2
            ? { items: [], total: 20, page: 2, page_size: 25 }
            : { items: [BOOKING], total: shrunk ? 20 : 30, page: 1, page_size: 25 }
        ) as never;
      }
      return Promise.resolve([]) as never;
    });
    const { Transactions } = await import("./Transactions");
    const { LanguageProvider } = await import("../i18n/LanguageProvider");
    const { screen } = await import("@testing-library/react");
    const { default: userEvent } = await import("@testing-library/user-event");
    render(
      <LanguageProvider>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <MemoryRouter>
            <Transactions />
          </MemoryRouter>
        </QueryClientProvider>
      </LanguageProvider>
    );
    await screen.findByText("Page 1 of 2");

    await userEvent.click(screen.getByRole("button", { name: "Next →" }));

    expect(await screen.findByText("Page 1 of 1")).toBeInTheDocument();
    expect(screen.queryByText("Page 2 of 1")).not.toBeInTheDocument();
  });
});

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
