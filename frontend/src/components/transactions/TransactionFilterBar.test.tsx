import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { SEARCH_DELAY_MS, TransactionFilterBar } from "./TransactionFilterBar";
import { LanguageProvider } from "../../i18n/LanguageProvider";
import type { PersistedFilters } from "../../state/filterStore";

const NO_FILTERS: PersistedFilters = {
  accountId: undefined,
  category: undefined,
  transactionType: undefined,
  start: undefined,
  end: undefined,
  search: undefined,
};

function bar(filters: PersistedFilters, onChange: (patch: Partial<PersistedFilters>) => void) {
  return (
    <LanguageProvider>
      <TransactionFilterBar filters={filters} onChange={onChange} onReset={() => {}} accounts={[]} categories={[]} />
    </LanguageProvider>
  );
}

const searchBox = () => screen.getByPlaceholderText("Search description…") as HTMLInputElement;

describe("TransactionFilterBar: search", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("filters once the typing pauses, not on every keystroke", () => {
    const onChange = vi.fn();
    render(bar(NO_FILTERS, onChange));

    for (const text of ["r", "re", "rew", "rewe"]) {
      fireEvent.change(searchBox(), { target: { value: text } });
      act(() => vi.advanceTimersByTime(SEARCH_DELAY_MS - 50));
    }
    expect(searchBox().value).toBe("rewe"); // what is typed shows at once
    expect(onChange).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(50));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ search: "rewe" });
  });

  it("clears the search filter when the box is emptied", () => {
    const onChange = vi.fn();
    render(bar({ ...NO_FILTERS, search: "rewe" }, onChange));

    fireEvent.change(searchBox(), { target: { value: "" } });
    act(() => vi.advanceTimersByTime(SEARCH_DELAY_MS));

    expect(onChange).toHaveBeenCalledWith({ search: undefined });
  });

  it("still applies what was typed when the page is left before the pause", () => {
    const onChange = vi.fn();
    const { unmount } = render(bar(NO_FILTERS, onChange));

    fireEvent.change(searchBox(), { target: { value: "rewe" } });
    unmount();

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ search: "rewe" });
    act(() => vi.advanceTimersByTime(SEARCH_DELAY_MS));
    expect(onChange).toHaveBeenCalledTimes(1); // not a second time by the timer
  });

  it("shows a search that was changed elsewhere (Reset) and doesn't send it back", () => {
    const onChange = vi.fn();
    const { rerender } = render(bar({ ...NO_FILTERS, search: "rewe" }, onChange));
    expect(searchBox().value).toBe("rewe");

    rerender(bar(NO_FILTERS, onChange));
    act(() => vi.advanceTimersByTime(SEARCH_DELAY_MS));

    expect(searchBox().value).toBe("");
    expect(onChange).not.toHaveBeenCalled();
  });
});
