import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Accounts } from "./Accounts";
import { Budgets } from "./Budgets";
import { CreditCards } from "./CreditCards";
import { ImportHistory } from "../components/imports/ImportHistory";
import { BackupSection } from "../components/settings/BackupSection";
import { LearnedRulesSection } from "../components/settings/LearnedRulesSection";
import { LanguageProvider } from "../i18n/LanguageProvider";
import { ApiError, apiGet } from "../api/client";

// The real hooks and API functions; only the requests themselves are stubbed.
vi.mock("../api/client", async (original) => ({
  ...(await original<typeof import("../api/client")>()),
  apiGet: vi.fn(),
}));

function show(page: ReactElement) {
  render(
    <LanguageProvider>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>{page}</MemoryRouter>
      </QueryClientProvider>
    </LanguageProvider>
  );
}

const PAGES: [string, ReactElement, RegExp][] = [
  ["credit cards", <CreditCards key="cards" />, /No credit-card accounts/i],
  ["budgets", <Budgets key="budgets" />, /No budgets/i],
  ["accounts", <Accounts key="accounts" />, /No accounts/i],
  ["import history", <ImportHistory key="history" />, /No imports/i],
];

describe("a list that could not be loaded", () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockReset(); // (in braces: a function returned from the hook would be called as its cleanup)
  });

  it.each(PAGES)("%s: says so, instead of claiming there is nothing", async (_name, page, emptyText) => {
    vi.mocked(apiGet).mockImplementation(async () => {
      throw new ApiError(0, "The app is not running.");
    });
    show(page);

    expect(await screen.findByRole("alert")).toHaveTextContent("The app is not running.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByText(emptyText)).not.toBeInTheDocument();
  });

  it.each([
    ["backups", <BackupSection key="backups" />],
    ["learned rules", <LearnedRulesSection key="rules" />],
  ] as [string, ReactElement][])("%s (settings): says so, instead of showing nothing", async (_name, section) => {
    vi.mocked(apiGet).mockImplementation(async () => {
      throw new ApiError(0, "The app is not running.");
    });
    show(section);

    expect(await screen.findByRole("alert")).toHaveTextContent("The app is not running.");
  });

  it.each(PAGES)("%s: still says there is nothing when that is what was loaded", async (_name, page, emptyText) => {
    vi.mocked(apiGet).mockImplementation((path: string) =>
      Promise.resolve(path === "/api/budgets/status" ? { month: "2026-11", items: [] } : []) as never
    );
    show(page);

    expect(await screen.findByText(emptyText)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
