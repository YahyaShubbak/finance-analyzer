import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import clsx from "clsx";
import { ImportReview } from "./ImportReview";
import { LanguageProvider } from "../../i18n/LanguageProvider";
import type { ImportPreview } from "../../types";

// Every row of the review asks clsx for its class names when it is drawn:
// counting the calls counts the rows drawn.
vi.mock("clsx", async (original) => {
  const real = (await original<typeof import("clsx")>()).default;
  return { default: vi.fn(real) };
});

const ROWS = 80;

function spreadsheet(): ImportPreview {
  const numbers = Array.from({ length: ROWS }, (_unused, i) => i);
  return {
    staging_id: "staged", filename: "march.csv", account_id: 1, account_name: "Giro", account_recognized: null,
    auto_import: false, review_reasons: [], page_count: 0, layout_lines: [],
    source_rows: [["Date", "Description", "Amount"], ...numbers.map((i) => ["2026-03-02", `Shop ${i}`, "-1.00"])],
    document_type: "bank_statement", detected_columns: {}, detected_layout: null, period_start: null, period_end: null,
    transaction_count: ROWS,
    transactions: numbers.map((i) => ({
      source_row_index: i, original_date_text: "2026-03-02", original_description: `Shop ${i}`,
      original_amount_text: "-1.00", original_currency_text: null, parsed_amount_minor: -100, parsed_date: "2026-03-02",
      parsed_currency: "EUR", counterparty: null, details: null, location: { row: i + 1 },
    })),
    issues: [], ambiguous: false, has_errors: false, statement_total_minor: null, other_totals: {}, total_check: null,
    available_columns: [], header_row_index: 0, date_format: null, date_format_candidates: [], decimal_separator: null,
    needs_decimal_separator: false,
    options: { column_mapping: null, header_row: null, date_format: null, decimal_separator: null, invert_signs: null },
    new_count: ROWS, exact_duplicate_count: 0, possible_duplicate_count: 0, needs_review_count: 0, unusable_row_count: 0,
    warning_count: 0, row_classifications: [],
  };
}

describe("ImportReview", () => {
  it("draws only the rows concerned when the mouse moves over a booking", async () => {
    Element.prototype.scrollIntoView = vi.fn();
    render(
      <LanguageProvider>
        <ImportReview preview={spreadsheet()} importing={false} canImport onImport={() => {}} onClose={() => {}} />
      </LanguageProvider>
    );
    const booking = (i: number) => screen.getAllByRole("row", { name: new RegExp(`Shop ${i} `) }).at(-1)!;
    await userEvent.hover(booking(3));
    expect(booking(3)).toHaveAttribute("aria-selected", "true");

    vi.mocked(clsx).mockClear();
    await userEvent.hover(booking(40));

    expect(booking(40)).toHaveAttribute("aria-selected", "true");
    expect(booking(3)).toHaveAttribute("aria-selected", "false");
    // two bookings and their two rows of the original — not all 80 of each
    expect(vi.mocked(clsx).mock.calls.length).toBeLessThan(20);
  });
});
