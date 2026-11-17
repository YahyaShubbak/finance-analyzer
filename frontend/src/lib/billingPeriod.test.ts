import { describe, expect, it } from "vitest";
import { billingMonths } from "./billingPeriod";

describe("billingMonths", () => {
  it("names the month a statement covers, not the day it spills over", () => {
    expect(billingMonths("2026-05-02", "2026-06-01")).toEqual(["2026-05"]);
    expect(billingMonths("2026-07-01", "2026-07-31")).toEqual(["2026-07"]);
  });
  it("names both months of a statement ending mid-month", () => {
    expect(billingMonths("2026-06-16", "2026-07-15")).toEqual(["2026-06", "2026-07"]);
    expect(billingMonths("2025-12-16", "2026-01-15")).toEqual(["2025-12", "2026-01"]);
  });
  it("falls back to the one date there is", () => {
    expect(billingMonths(null, "2026-07-15")).toEqual(["2026-07"]);
    expect(billingMonths(null, null)).toEqual([]);
  });
});
