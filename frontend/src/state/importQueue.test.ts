import { describe, expect, it } from "vitest";
import { MAX_PARALLEL_UPLOADS, isSameImport, uploadSlot } from "./importQueue";
import type { ImportCommitResult, ImportRecord } from "../types";

function committed(importId: number, filename: string): ImportCommitResult {
  return {
    import_id: importId,
    filename,
    transactions_created: 3,
    duplicates_flagged: 0,
    rows_skipped: 0,
    credit_card_statement_id: null,
    transactions_enriched: 0,
  };
}

function record(id: number, filename: string): ImportRecord {
  return {
    id,
    filename,
    document_type: "bank_statement",
    account_id: 1,
    account_name: "Giro",
    imported_at: "2026-03-01T10:00:00+00:00",
    period_start: null,
    period_end: null,
    status: "imported",
    detected_transaction_count: 3,
  };
}

describe("isSameImport (may a card still undo its import?)", () => {
  it("is the card's import while the list has it under its number and name", () => {
    expect(isSameImport(committed(7, "march.csv"), [record(6, "february.csv"), record(7, "march.csv")])).toBe(true);
  });

  it("is gone once it was removed from the list", () => {
    expect(isSameImport(committed(7, "march.csv"), [record(6, "february.csv")])).toBe(false);
  });

  it("is not another import that has its number now (removed and imported anew, or a restored backup)", () => {
    expect(isSameImport(committed(7, "march.csv"), [record(7, "april.csv")])).toBe(false);
  });

  it("is unknown — so not undone — while the list isn't loaded", () => {
    expect(isSameImport(committed(7, "march.csv"), undefined)).toBe(false);
  });
});

describe("uploadSlot (a few uploads at a time)", () => {
  it("gives the next one its turn when an upload is over", async () => {
    expect(MAX_PARALLEL_UPLOADS).toBe(2);
    const turns: string[] = [];
    const first = await uploadSlot();
    const second = await uploadSlot();
    void uploadSlot().then((release) => {
      turns.push("third");
      release();
    });
    await Promise.resolve();
    expect(turns).toEqual([]); // two are uploading: the third waits

    first();
    first(); // ending a turn twice does not give two turns away
    await Promise.resolve();
    await Promise.resolve();
    expect(turns).toEqual(["third"]);

    second();
    const again = await uploadSlot(); // all free again
    again();
  });
});
