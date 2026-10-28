import { beforeAll, describe, expect, it } from "vitest";
import { describeDateFormat, formatDateTime, formatMoney, setFormatLocale, toLocalIsoDate } from "./format";
import { formatErrorDetail } from "../api/client";
import { datePresets } from "./datePresets";
import { translate, type MessageKey } from "../i18n/core";

describe("formatMoney", () => {
  beforeAll(() => setFormatLocale("de-DE"));

  it("formats ISO currencies", () => {
    expect(formatMoney(123456, "EUR")).toMatch(/1\.234,56\s€/);
  });

  it("never throws for non-ISO currency values", () => {
    expect(() => formatMoney(4290, "€")).not.toThrow();
    expect(formatMoney(4290, "Euro")).toBe("42,90 Euro");
  });
});

describe("local dates", () => {
  it("uses the local calendar day, not UTC", () => {
    // 00:30 local time on 1 March — in UTC+1/+2 this is still 28/29 Feb in UTC.
    expect(toLocalIsoDate(new Date(2026, 2, 1, 0, 30))).toBe("2026-03-01");
  });

  it("date presets start on the first of the local month/year", () => {
    const presets = datePresets(new Date(2026, 8, 1, 0, 15));
    expect(presets["This month"]).toEqual({ start: "2026-09-01", end: "2026-09-01" });
    expect(presets["Year to date"].start).toBe("2026-01-01");
    expect(presets["Last 3 months"].start).toBe("2026-07-01");
  });

  it("treats backend timestamps without offset as UTC", () => {
    expect(formatDateTime("2026-03-01T12:00:00")).toBe(formatDateTime("2026-03-01T12:00:00Z"));
  });

  it("describes strptime formats in the chosen language", () => {
    const en = (key: MessageKey) => translate("en", key);
    const de = (key: MessageKey) => translate("de", key);
    expect(describeDateFormat("%d/%m/%Y", en)).toBe("DD/MM/YYYY");
    expect(describeDateFormat("%m/%d/%y", en)).toBe("MM/DD/YY");
    expect(describeDateFormat("%d.%m.%Y", de)).toBe("TT.MM.JJJJ");
  });
});

describe("formatErrorDetail", () => {
  it("passes plain strings through", () => {
    expect(formatErrorDetail("Account not found", "x")).toBe("Account not found");
  });

  it("turns FastAPI validation lists into readable text (not [object Object])", () => {
    const detail = [{ loc: ["body", "iban"], msg: "Value error, IBAN check digits are wrong", type: "value_error" }];
    expect(formatErrorDetail(detail, "x")).toBe("IBAN: IBAN check digits are wrong"); // the field as the user knows it
  });

  it("falls back for unknown shapes", () => {
    expect(formatErrorDetail({ foo: 1 }, "Bad Request")).toBe("Bad Request");
  });
});
