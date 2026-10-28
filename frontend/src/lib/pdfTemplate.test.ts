import { describe, expect, it } from "vitest";
import { columnsFrom, normalizeLine, suggestRoles } from "./pdfTemplate";

const words = (...items: [string, number, number][]) => items.map(([text, x0, x1]) => ({ text, x0, x1 }));

describe("teaching the PDF reader", () => {
  it("guesses the roles of a booking line's words", () => {
    const line = words(["03.05.", 40, 62], ["04.05.", 70, 92], ["Bäckerei", 150, 185], ["Nord", 188, 205], ["4,80", 452, 470], ["S", 474, 479]);
    expect(suggestRoles(line)).toEqual(["date", "value_date", "text", "text", "amount", "sign"]);
  });

  it("takes the last amount, and a lone date as the purchase date", () => {
    const line = words(["12.05.2026", 40, 85], ["Tankstelle", 150, 191], ["12,00", 300, 320], ["61,23", 447, 470]);
    expect(suggestRoles(line)).toEqual(["date", "text", "text", "amount"]);
  });

  it("spans each column from its first to its last word", () => {
    const line = words(["03.05.", 40, 62], ["Bäckerei", 150, 185], ["Nord", 188, 205], ["4,80", 452, 470]);
    expect(columnsFrom(line, ["date", "text", "text", "amount"])).toEqual({
      date: [40, 62],
      text: [150, 205],
      amount: [452, 470],
    });
    expect(columnsFrom(line, [null, "text", null, "amount"])).toEqual({ text: [150, 185], amount: [452, 470] });
  });

  it("recognizes a line again whatever its numbers", () => {
    expect(normalizeLine("+61 Beispiel Punkte")).toBe(normalizeLine("+5 BEISPIEL PUNKTE"));
    expect(normalizeLine("Neuer Saldo zum 31.05.2026  1.234,56")).toBe("NEUER SALDO ZUM");
  });
});
