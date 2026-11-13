import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Overview } from "./Overview";
import { LanguageProvider } from "../i18n/LanguageProvider";
import { ApiError, apiGet } from "../api/client";

// The real hooks and API functions; only the requests themselves are stubbed.
vi.mock("../api/client", async (original) => ({
  ...(await original<typeof import("../api/client")>()),
  apiGet: vi.fn(),
}));

describe("Overview", () => {
  it("asks for the recurring payments and the forecast of the chosen account", async () => {
    localStorage.setItem("finance.dashboard.v1", JSON.stringify({ preset: "This month", accountId: 5 }));
    vi.mocked(apiGet).mockImplementation((path: string) => {
      if (path === "/api/accounts") {
        return Promise.resolve([
          { id: 5, name: "Giro", account_type: "checking", currency: "EUR", is_archived: false, transaction_count: 0 },
        ]) as never;
      }
      return Promise.reject(new Error(`not part of this test: ${path}`)) as never;
    });

    render(
      <LanguageProvider>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <MemoryRouter>
            <Overview />
          </MemoryRouter>
        </QueryClientProvider>
      </LanguageProvider>
    );

    // like every other figure on the page ("for the chosen period and account")
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith("/api/analytics/totals", expect.objectContaining({ account_id: "5" })));
    expect(apiGet).toHaveBeenCalledWith("/api/recurring/series", { account_id: "5" });
    expect(apiGet).toHaveBeenCalledWith("/api/recurring/forecast", { months: 3, account_id: "5" });
  });

  it.each([
    ["the months", "/api/analytics/over-time", "Not enough data yet"],
    ["the categories", "/api/analytics/by-category", "No expenses"],
    ["the accounts", "/api/analytics/by-account", "No activity"],
    ["the forecast", "/api/recurring/forecast", "Not enough data yet"],
  ])("says that %s could not be loaded, instead of claiming there is nothing", async (_part, failing, emptyText) => {
    localStorage.clear();
    const answers: Record<string, unknown> = {
      "/api/accounts": [],
      "/api/analytics/totals": {
        is_mixed_currency: false, currency: "EUR", income_minor: 100000, expenses_minor: 40000, net_minor: 60000,
        transaction_count: 12, by_currency: null,
      },
      "/api/analytics/over-time": [],
      "/api/analytics/by-category": [],
      "/api/analytics/by-account": [],
      "/api/analytics/transfers-summary": { transfer_count: 0 },
      "/api/recurring/series": { series: [] },
      "/api/recurring/forecast": { points: [] },
    };
    vi.mocked(apiGet).mockImplementation((path: string) => {
      if (path === failing) return Promise.reject(new ApiError(500, `Could not read ${failing}`)) as never;
      if (path in answers) return Promise.resolve(answers[path]) as never;
      return Promise.reject(new Error(`not part of this test: ${path}`)) as never;
    });

    render(
      <LanguageProvider>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <MemoryRouter>
            <Overview />
          </MemoryRouter>
        </QueryClientProvider>
      </LanguageProvider>
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(`Could not read ${failing}`);
    expect(alert).toHaveTextContent("Try again");
    // the other parts loaded: each says what it has (here: nothing) — the failed one does not
    const empties = screen.queryAllByText(new RegExp(emptyText, "i"));
    expect(empties.length).toBe(emptyText === "Not enough data yet" ? 1 : 0);
  });
});
