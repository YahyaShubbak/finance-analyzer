import { beforeEach, describe, expect, it } from "vitest";
import { renderHook } from "@testing-library/react";
import { useDashboardPeriod } from "./dashboardPeriod";
import { datePresets } from "../lib/datePresets";

const KEY = "finance.dashboard.v1";

describe("useDashboardPeriod", () => {
  beforeEach(() => {
    localStorage.removeItem(KEY);
  });

  it("falls back to this month for a stored preset it does not know", () => {
    localStorage.setItem(KEY, JSON.stringify({ preset: "A preset of another version", accountId: 5 }));

    const { result } = renderHook(() => useDashboardPeriod());

    expect(result.current.range).toEqual(datePresets()["This month"]);
    expect(result.current.accountId).toBe(5); // the rest of what was remembered stays
  });

  it("keeps a stored preset it knows", () => {
    localStorage.setItem(KEY, JSON.stringify({ preset: "Last 3 months" }));

    const { result } = renderHook(() => useDashboardPeriod());

    expect(result.current.range).toEqual(datePresets()["Last 3 months"]);
  });
});
