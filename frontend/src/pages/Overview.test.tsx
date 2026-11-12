import { describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Overview } from "./Overview";
import { LanguageProvider } from "../i18n/LanguageProvider";
import { apiGet } from "../api/client";

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
});
