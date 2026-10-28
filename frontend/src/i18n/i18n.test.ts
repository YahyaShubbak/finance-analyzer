import { describe, expect, it } from "vitest";
import { de } from "./de";
import { en, type MessageKey } from "./en";
import { translate } from "./core";

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe("translations", () => {
  const keys = Object.keys(en) as MessageKey[];

  it("German has exactly the English keys", () => {
    expect(Object.keys(de).sort()).toEqual([...keys].sort());
  });

  it("uses the same placeholders in both languages", () => {
    for (const key of keys) {
      expect({ key, names: placeholders(de[key]) }).toEqual({ key, names: placeholders(en[key]) });
    }
  });

  it("has no empty texts", () => {
    for (const key of keys) {
      expect({ key, empty: !de[key].trim() || !en[key].trim() }).toEqual({ key, empty: false });
    }
  });

  it("has a plural form for every singular", () => {
    for (const key of keys.filter((k) => k.endsWith(".one"))) {
      expect(keys).toContain(key.replace(/\.one$/, ".other"));
    }
  });

  it("fills placeholders", () => {
    expect(translate("de", "tx.page", { page: 2, pages: 5 })).toBe("Seite 2 von 5");
    expect(translate("en", "tx.page", { page: 2, pages: 5 })).toBe("Page 2 of 5");
  });
});
