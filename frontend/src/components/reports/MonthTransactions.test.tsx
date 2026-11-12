import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MonthTransactions } from "./MonthTransactions";
import { LanguageProvider } from "../../i18n/LanguageProvider";
import { apiGet } from "../../api/client";

vi.mock("../../api/client", async (original) => ({
  ...(await original<typeof import("../../api/client")>()),
  apiGet: vi.fn(),
}));

// jsdom has no layout: the list scrolls itself into view when it opens
Element.prototype.scrollIntoView = vi.fn();

const BOOKING = {
  id: 1, account_id: 1, account_name: "Giro", transaction_date: "2026-03-01", normalized_description: "Shop",
  merchant: "Shop", category: "Groceries", amount_minor: -1000, currency: "EUR", transaction_type: "expense",
  is_duplicate: false, is_transfer: false, needs_review: false, review_reason: null, notes: null,
};

it("shows the last page that exists when the month’s list got shorter", async () => {
  // 30 bookings (two pages), but by the time page 2 is asked for only 20 are left
  vi.mocked(apiGet).mockImplementation((path: string, params?: Record<string, unknown>) => {
    if (path !== "/api/transactions") return Promise.resolve([]) as never;
    const shrunk = vi.mocked(apiGet).mock.calls.some(([p, q]) => p === path && (q as { page?: number })?.page === 2);
    return Promise.resolve(
      params?.page === 2
        ? { items: [], total: 20, page: 2, page_size: 25 }
        : { items: [BOOKING], total: shrunk ? 20 : 30, page: 1, page_size: 25 }
    ) as never;
  });
  render(
    <LanguageProvider>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <MonthTransactions
            point={{ month: "2026-03", currency: "EUR", income_minor: 0, expenses_minor: 30000 }}
            currency="EUR"
            onClose={() => {}}
          />
        </MemoryRouter>
      </QueryClientProvider>
    </LanguageProvider>
  );
  await screen.findByText("Page 1 of 2");

  await userEvent.click(screen.getByRole("button", { name: "Next →" }));

  expect(await screen.findByText("Page 1 of 1")).toBeInTheDocument();
  expect(screen.queryByText("Page 2 of 1")).not.toBeInTheDocument();
});
