import { describe, expect, it, vi } from "vitest";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ResetSection } from "./ResetSection";
import { LanguageProvider } from "../../i18n/LanguageProvider";
import { useFilters } from "../../state/filterStore";
import { resetEverything } from "../../api/system";

vi.mock("../../api/system");
vi.mock("../../api/backup");

describe("ResetSection", () => {
  it("forgets the filters in use and the dashboard's period, not only their stored copies", async () => {
    vi.mocked(resetEverything).mockResolvedValue({ rows_deleted: 10, files_deleted: 2 });
    const filters = renderHook(() => useFilters());
    act(() => filters.result.current[1]({ search: "rewe", start: "2026-01-01" }));
    localStorage.setItem("finance.dashboard.v1", JSON.stringify({ preset: "Last month", accountId: 5 }));

    render(
      <LanguageProvider>
        <QueryClientProvider client={new QueryClient()}>
          <ResetSection />
        </QueryClientProvider>
      </LanguageProvider>
    );
    await userEvent.click(screen.getByRole("button", { name: "Reset everything…" }));
    await userEvent.type(screen.getByLabelText("Type DELETE to confirm"), "DELETE");
    await userEvent.click(screen.getByRole("button", { name: "Delete everything for good" }));
    await waitFor(() => expect(resetEverything).toHaveBeenCalledWith(false));
    await screen.findByText("Everything was deleted. The app is like new.");

    expect(localStorage.getItem("finance.dashboard.v1")).toBeNull();
    expect(filters.result.current[0].search).toBeUndefined();

    // The next change of a filter must not bring the old ones back (the
    // Transactions page writes all of them whenever one changes).
    act(() => filters.result.current[1]({ accountId: 3 }));
    const stored = JSON.parse(localStorage.getItem("finance.filters.v1") ?? "{}");
    expect(stored.accountId).toBe(3);
    expect(stored.search).toBeUndefined();
    expect(stored.start).toBeUndefined();
  });
});
