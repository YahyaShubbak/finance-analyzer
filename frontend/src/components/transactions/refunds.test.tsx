import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LanguageProvider } from "../../i18n/LanguageProvider";
import { CategoryCell } from "./CategoryCell";
import { CategoryBreakdownList } from "../reports/CategoryBreakdownList";
import { BreakdownTransactions } from "../reports/BreakdownTransactions";
import { useCategoryAssignment } from "../../hooks/useCategoryAssignment";
import { countingOf } from "../../lib/categories";
import { listCategories } from "../../api/categories";
import { updateTransaction } from "../../api/transactions";
import { createCategoryRule } from "../../api/rules";
import type { Transaction } from "../../types";

// The real components and hooks; only the requests to the backend are stubbed.
vi.mock("../../api/categories");
vi.mock("../../api/transactions");
vi.mock("../../api/rules");

function Providers({ children }: { children: ReactNode }) {
  return (
    <LanguageProvider>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        {children}
      </QueryClientProvider>
    </LanguageProvider>
  );
}

/** Travel costs reimbursed by the employer, as they arrive: income. */
function booking(overrides: Partial<Transaction>): Transaction {
  return {
    id: 7, account_id: 1, account_name: "Giro", transaction_date: "2026-03-20",
    normalized_description: "Arbeitgeber GmbH Reisekostenerstattung", merchant: "Arbeitgeber GmbH",
    category: "Other Income", amount_minor: 120000, currency: "EUR", transaction_type: "income",
    is_duplicate: false, is_transfer: false, needs_review: false, review_reason: null, notes: null,
    source_filename: "march.csv", country: null, city: null, online: false,
    ...overrides,
  } as Transaction;
}

beforeEach(() => {
  for (const request of [listCategories, updateTransaction, createCategoryRule]) vi.mocked(request).mockReset();
  vi.mocked(listCategories).mockResolvedValue([]);
});

describe("how a booking that came in counts", () => {
  it("is asked when it gets a category of spending", () => {
    expect(countingOf(booking({}), "Travel")).toBe("ask");
    expect(countingOf(booking({ category: "Travel" }), "Travel")).toBe("ask"); // counted as income so far
    expect(countingOf(booking({}), "My own category")).toBe("ask");
  });

  it("is not asked about where there is nothing to decide", () => {
    expect(countingOf(booking({}), "Salary")).toBeNull(); // income stays income
    expect(countingOf(booking({ amount_minor: -5000, transaction_type: "expense" }), "Travel")).toBeNull();
    expect(countingOf(booking({ transaction_type: "expense", category: "Travel" }), "Food")).toBeNull(); // stays a refund
    expect(countingOf(booking({ is_transfer: true, transaction_type: "transfer" }), "Travel")).toBeNull();
    expect(countingOf(booking({}), "Transfers")).toBeNull();
  });

  it("makes a refund that gets a category of income income again", () => {
    expect(countingOf(booking({ transaction_type: "expense", category: "Travel" }), "Other Income")).toBe("income");
  });
});

describe("CategoryCell", () => {
  it("asks whether money that came in is a refund or income", async () => {
    const onAssign = vi.fn();
    render(<CategoryCell transaction={booking({})} busy={false} onAssign={onAssign} />, { wrapper: Providers });

    await userEvent.click(screen.getByRole("button", { name: /Category of/ }));
    await userEvent.click(screen.getByRole("button", { name: "Travel" }));
    expect(onAssign).not.toHaveBeenCalled();
    expect(screen.getByText(/came in\. How should it count\?/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /As a refund of Travel/ }));
    expect(onAssign).toHaveBeenCalledWith(expect.objectContaining({ id: 7 }), "Travel", "refund");
  });

  it("turns a booking counted as income into a refund, also in its own category", async () => {
    const onAssign = vi.fn();
    render(<CategoryCell transaction={booking({ category: "Travel" })} busy={false} onAssign={onAssign} />, {
      wrapper: Providers,
    });
    await userEvent.click(screen.getByRole("button", { name: /Category of/ }));
    await userEvent.click(screen.getByRole("button", { name: "Travel" }));
    await userEvent.click(screen.getByRole("button", { name: /As a refund of Travel/ }));
    expect(onAssign).toHaveBeenCalledWith(expect.anything(), "Travel", "refund");
  });

  it("goes back to the categories, and asks nothing for a category of income", async () => {
    const onAssign = vi.fn();
    render(<CategoryCell transaction={booking({ category: "Food" })} busy={false} onAssign={onAssign} />, {
      wrapper: Providers,
    });
    await userEvent.click(screen.getByRole("button", { name: /Category of/ }));
    await userEvent.click(screen.getByRole("button", { name: "Travel" }));
    await userEvent.click(screen.getByRole("button", { name: "Back to the categories" }));
    await userEvent.click(screen.getByRole("button", { name: "Salary" }));
    expect(onAssign).toHaveBeenCalledWith(expect.anything(), "Salary", undefined);
  });
});

describe("saving how it counts", () => {
  it("changes this booking only: a refund is never learned for its payer", async () => {
    vi.mocked(updateTransaction).mockResolvedValue(booking({ category: "Travel", transaction_type: "expense" }));
    const { result } = renderHook(() => useCategoryAssignment(), { wrapper: Providers });
    act(() => result.current.setLearn(true));

    act(() => result.current.assign(booking({}), "Travel", "refund"));

    await waitFor(() => expect(result.current.notice).toEqual({ kind: "refund", category: "Travel" }));
    expect(updateTransaction).toHaveBeenCalledWith(7, { category: "Travel", transaction_type: "expense" });
    // (the employer who reimburses travel pays the salary, too)
    expect(createCategoryRule).not.toHaveBeenCalled();
  });

  it("changes only the type when the category stays", async () => {
    vi.mocked(updateTransaction).mockResolvedValue(booking({ category: "Travel", transaction_type: "expense" }));
    const { result } = renderHook(() => useCategoryAssignment(), { wrapper: Providers });

    act(() => result.current.assign(booking({ category: "Travel" }), "Travel", "refund"));

    await waitFor(() => expect(updateTransaction).toHaveBeenCalledWith(7, { transaction_type: "expense" }));
  });
});

describe("a category with refunds", () => {
  it("says in the list what was refunded", () => {
    render(
      <CategoryBreakdownList
        data={[{ category: "Travel", currency: "EUR", amount_minor: 0, refunded_minor: 120000 }]}
        currency="EUR"
        selected={null}
        onSelect={() => {}}
      />,
      { wrapper: Providers }
    );
    expect(screen.getByText(/1,200\.00 refunded/)).toBeInTheDocument();
  });

  it("says among its bookings what was spent, refunded and paid oneself", async () => {
    Element.prototype.scrollIntoView = vi.fn();
    const fetchPage = vi.fn(async () => ({
      items: [], total: 3, page: 1, page_size: 25, amount_minor: 20000, spent_minor: 140000, refunded_minor: 120000,
    }));
    render(
      <BreakdownTransactions
        title="Travel"
        currency="EUR"
        queryKey={["travel"]}
        fetchPage={fetchPage}
        emptyText="none"
        onClose={() => {}}
      />,
      { wrapper: Providers }
    );
    expect(await screen.findByText(/Spent .1,400\.00, refunded .1,200\.00, paid yourself .200\.00/)).toBeInTheDocument();
  });
});
