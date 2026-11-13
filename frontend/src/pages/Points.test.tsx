import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Points } from "./Points";
import { LanguageProvider } from "../i18n/LanguageProvider";
import { apiGet } from "../api/client";
import { currencySymbol } from "../lib/format";

// The real page, hooks and API functions; only the requests themselves are stubbed.
vi.mock("../api/client", async (original) => ({
  ...(await original<typeof import("../api/client")>()),
  apiGet: vi.fn(),
}));

const program = {
  id: 1, name: "Shop Punkte", unit: "Punkte", value_per_100: 100, value_set_by_user: false, currency: "CHF",
  balance: 555, balance_value_minor: 555, balance_stated: true, balance_as_of: "2026-03-31", earned: 55, redeemed: -500,
  earned_this_year: 55, redeemed_this_year: -500, cashback_percent: 1,
  months: [{ month: "2026-03", earned: 55, redeemed: -500, balance: 555 }],
  merchants: [{ merchant: "Buchladen Beispiel", points: 50, bookings: 2, spent_minor: 5000 }],
  redemptions: [{ date: "2026-03-20", points: -500, value_minor: 500 }],
  bookings: [],
};

describe("Points", () => {
  it("shows what the points are worth in the card's currency, not always in euros", async () => {
    vi.mocked(apiGet).mockImplementation((path: string) =>
      (path === "/api/points" ? Promise.resolve([program]) : Promise.reject(new Error(`not part of this test: ${path}`))) as never
    );
    render(
      <LanguageProvider>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <MemoryRouter>
            <Points />
          </MemoryRouter>
        </QueryClientProvider>
      </LanguageProvider>
    );

    expect((await screen.findAllByText(/≈\s*CHF\s*5\.55/)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/€/)).not.toBeInTheDocument();
    expect(screen.getByText(/CHF\s*5\.00/)).toBeInTheDocument(); // the redemption's value
    expect(screen.getByText("per CHF")).toBeInTheDocument();
  });

  it("writes a currency as amounts do", () => {
    expect(currencySymbol("EUR")).toBe("€");
    expect(currencySymbol("CHF")).toBe("CHF");
    expect(currencySymbol("not a currency")).toBe("not a currency");
  });
});
