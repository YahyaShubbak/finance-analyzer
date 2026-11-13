import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "../i18n/LanguageProvider";
import { AccountRow } from "./accounts/AccountRow";
import { BudgetProgressRow } from "./budgets/BudgetProgressRow";
import { clickedIndex } from "../lib/chartClick";
import { useCategoryAssignment } from "../hooks/useCategoryAssignment";
import { updateAccount } from "../api/accounts";
import { deleteBudget, listBudgets } from "../api/budgets";
import { createCategoryRule } from "../api/rules";
import { ApiError, retryQuery } from "../api/client";
import type { Account, Transaction } from "../types";

// The real components and hooks; only the requests to the backend are stubbed.
vi.mock("../api/accounts");
vi.mock("../api/budgets");
vi.mock("../api/rules");

function Providers({ children }: { children: ReactNode }) {
  return (
    <LanguageProvider>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        {children}
      </QueryClientProvider>
    </LanguageProvider>
  );
}

beforeEach(() => {
  for (const request of [updateAccount, deleteBudget, listBudgets, createCategoryRule]) vi.mocked(request).mockReset();
});

describe("removing a budget", () => {
  it("asks first — one click removes nothing", async () => {
    vi.mocked(listBudgets).mockResolvedValue([{ id: 4, category: "Groceries", amount_minor: 30000, currency: "EUR" }] as never);
    vi.mocked(deleteBudget).mockResolvedValue(undefined as never);
    const item = { category: "Groceries", budget_minor: 30000, actual_minor: 1000, remaining_minor: 29000,
                   percent_used: 3, over_budget: false, currency: "EUR" };
    render(<BudgetProgressRow item={item} />, { wrapper: Providers });

    await userEvent.click(await screen.findByRole("button", { name: "Remove" }));
    expect(deleteBudget).not.toHaveBeenCalled();
    expect(screen.getByText("Remove the budget for Groceries?")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(deleteBudget).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    await userEvent.click(screen.getByRole("button", { name: "Yes, remove it" }));
    await waitFor(() => expect(deleteBudget).toHaveBeenCalledWith(4));
  });
});

describe("archiving an account", () => {
  it("says why it failed", async () => {
    vi.mocked(updateAccount).mockRejectedValue(new ApiError(0, "The app is not running."));
    const account: Account = {
      id: 1, name: "Giro", account_type: "checking", currency: "EUR", iban: null, created_at: "2026-01-01T00:00:00",
      is_archived: false, transaction_count: 0, transactions_balance_minor: 0, opening_balance_minor: null,
      opening_balance_date: null, current_balance_minor: 0,
    };
    render(<table><tbody><AccountRow account={account} /></tbody></table>, { wrapper: Providers });

    await userEvent.click(screen.getByRole("button", { name: "Archive" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The app is not running.");
  });
});

describe("a click on the income/expense chart", () => {
  it("chooses the column it hit, and none when it hit none", () => {
    expect(clickedIndex(2)).toBe(2);
    expect(clickedIndex("0")).toBe(0);
    // beside the columns: read as a number these would be 0, the first month
    expect(clickedIndex(null)).toBeNull();
    expect(clickedIndex(undefined)).toBeNull();
    expect(clickedIndex("")).toBeNull();
  });
});

describe("requests the query cache repeats", () => {
  it("tries once more when no answer came or the server failed — not when it refused", () => {
    expect(retryQuery(0, new ApiError(0, "offline"))).toBe(true);
    expect(retryQuery(0, new ApiError(500, "server error"))).toBe(true);
    expect(retryQuery(1, new ApiError(500, "server error"))).toBe(false);
    expect(retryQuery(0, new ApiError(404, "Unknown account"))).toBe(false);
    expect(retryQuery(0, new ApiError(422, "not a valid IBAN"))).toBe(false);
  });
});

describe("assigning categories quickly one after the other", () => {
  it("still says that the first one failed", async () => {
    let failFirst!: (reason: Error) => void;
    vi.mocked(createCategoryRule)
      .mockReturnValueOnce(new Promise((_resolve, reject) => (failFirst = reject)) as never)
      .mockResolvedValueOnce({ category_rule: null, applied_to: 0 } as never);
    const { result } = renderHook(() => useCategoryAssignment(), { wrapper: Providers });
    act(() => result.current.setLearn(true));

    act(() => result.current.assign({ id: 1 } as Transaction, "Groceries"));
    act(() => result.current.assign({ id: 2 } as Transaction, "Dining"));
    await waitFor(() => expect(createCategoryRule).toHaveBeenCalledTimes(2));
    await act(async () => failFirst(new Error("Unknown transaction_id=1")));

    await waitFor(() => expect(result.current.error?.message).toBe("Unknown transaction_id=1"));
    expect(result.current.savingId).toBeNull();
  });
});
