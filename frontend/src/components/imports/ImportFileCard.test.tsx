import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ImportFileCards } from "./ImportFileCards";
import { LanguageProvider } from "../../i18n/LanguageProvider";
import { commitImport, discardStagedImport, listImports, previewImport, removeImport } from "../../api/imports";
import { listAccounts } from "../../api/accounts";
import { addFiles, clearQueue, saveSnapshot, type CardSnapshot } from "../../state/importQueue";
import type { ImportCommitResult, ImportPreview, ImportRecord } from "../../types";

// The real cards, hooks, queue and query cache; only the requests to the backend are stubbed.
vi.mock("../../api/imports");
vi.mock("../../api/accounts");

const committed: ImportCommitResult = {
  import_id: 7,
  filename: "march.csv",
  transactions_created: 3,
  duplicates_flagged: 0,
  rows_skipped: 0,
  credit_card_statement_id: null,
  transactions_enriched: 0,
};

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

/** A file read without anything to check, for the account "Giro". */
function preview(filename: string, overrides: Partial<ImportPreview> = {}): ImportPreview {
  return {
    staging_id: `staged-${filename}`,
    filename,
    account_id: 1,
    account_name: "Giro",
    account_recognized: "history",
    auto_import: false,
    review_reasons: [],
    page_count: 0,
    layout_lines: [],
    source_rows: [],
    document_type: "bank_statement",
    detected_columns: {},
    detected_layout: null,
    period_start: null,
    period_end: null,
    transaction_count: 1,
    transactions: [
      {
        source_row_index: 0,
        original_date_text: "2026-03-02",
        original_description: "Buchladen Beispiel",
        original_amount_text: "-40.00",
        original_currency_text: null,
        parsed_amount_minor: -4000,
        parsed_date: "2026-03-02",
        parsed_currency: "EUR",
        counterparty: null,
        details: null,
        location: { row: 1 },
      },
    ],
    issues: [],
    ambiguous: false,
    has_errors: false,
    statement_total_minor: null,
    other_totals: {},
    total_check: null,
    available_columns: [],
    header_row_index: 0,
    date_format: null,
    date_format_candidates: [],
    decimal_separator: null,
    needs_decimal_separator: false,
    options: { column_mapping: null, header_row: null, date_format: null, decimal_separator: null, invert_signs: null },
    new_count: 1,
    exact_duplicate_count: 0,
    possible_duplicate_count: 0,
    needs_review_count: 0,
    unusable_row_count: 0,
    warning_count: 0,
    row_classifications: [],
    ...overrides,
  };
}

/** ... of a kind not checked yet: its review opens by itself. */
function toCheck(filename: string): ImportPreview {
  return preview(filename, {
    review_reasons: ["new_kind"],
    source_rows: [
      ["Date", "Description", "Amount"],
      ["2026-03-02", "Buchladen Beispiel", "-40.00"],
    ],
  });
}

/** A file in the queue, as far as `snapshot` says. */
function queued(filename: string, snapshot?: CardSnapshot): string {
  const [key] = addFiles([new File(["date,amount"], filename)]);
  if (snapshot) saveSnapshot(key, snapshot);
  return key;
}

/** The imports page's cards. Unmounting them is leaving the page. */
function openPage(autoImport = false) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const page = render(
    <LanguageProvider>
      <QueryClientProvider client={queryClient}>
        <ImportFileCards autoImport={autoImport} />
      </QueryClientProvider>
    </LanguageProvider>
  );
  return { queryClient, leave: page.unmount };
}

/** A request the test answers when it wants to. */
function pending<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const undoButton = () => screen.getByRole("button", { name: "Undo" });

beforeEach(() => {
  clearQueue();
  for (const request of [commitImport, discardStagedImport, listImports, previewImport, removeImport, listAccounts]) {
    vi.mocked(request).mockReset();
  }
  vi.mocked(listAccounts).mockResolvedValue([]);
  vi.mocked(listImports).mockResolvedValue([]);
  vi.mocked(discardStagedImport).mockResolvedValue(undefined as never);
});

describe("ImportFileCard: undoing the import a card made", () => {
  beforeEach(() => {
    vi.mocked(removeImport).mockResolvedValue({
      import_id: 7,
      filename: "march.csv",
      transactions_removed: 3,
      raw_transactions_removed: 3,
      transfer_partners_reverted: 0,
      statements_removed: 0,
      reconciliations_recomputed: 0,
    });
  });

  it("removes its own import while the list of imports has it", async () => {
    vi.mocked(listImports).mockResolvedValue([record(6, "february.csv"), record(7, "march.csv")]);
    queued("march.csv", { committed });
    openPage();

    await waitFor(() => expect(undoButton()).toBeEnabled());
    await userEvent.click(undoButton());

    await waitFor(() => expect(removeImport).toHaveBeenCalledWith(7));
    expect(await screen.findByText(/Import undone/)).toBeInTheDocument();
  });

  it("never removes another import that has its number now", async () => {
    vi.mocked(listImports).mockResolvedValue([record(7, "march.csv")]);
    queued("march.csv", { committed });
    const { queryClient, leave } = openPage();
    await waitFor(() => expect(undoButton()).toBeEnabled());

    // removed in the list — and the next import (another file) got number 7
    vi.mocked(listImports).mockResolvedValue([record(7, "april.csv")]);
    await queryClient.invalidateQueries({ queryKey: ["imports"] });

    expect(await screen.findByText(/Import undone/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
    // ... also not after the page was left and opened again
    leave();
    openPage();
    expect(await screen.findByText(/Import undone/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
    expect(removeImport).not.toHaveBeenCalled();
  });

  it("forgets an import that was gone when the page was opened again", async () => {
    vi.mocked(listImports).mockResolvedValue([record(6, "february.csv")]);
    queued("march.csv", { committed, seenInHistory: true });
    openPage();

    expect(await screen.findByText(/Import undone/)).toBeInTheDocument();
    expect(removeImport).not.toHaveBeenCalled();
  });

  it("offers no undo while the list doesn't show its import (yet)", async () => {
    vi.mocked(listImports).mockResolvedValue([record(6, "february.csv")]);
    queued("march.csv", { committed });
    openPage();

    await waitFor(() => expect(listImports).toHaveBeenCalled());
    // just imported: the list is read again in a moment — the card stays as it is
    expect(screen.getByText("Imported")).toBeInTheDocument();
    expect(undoButton()).toBeDisabled();
    await userEvent.click(undoButton());
    expect(removeImport).not.toHaveBeenCalled();
  });
});

describe("ImportFileCard: many files dropped at once", () => {
  it("uploads two at a time; the others wait for their turn", async () => {
    const uploads = [1, 2, 3, 4].map(() => pending<ImportPreview>());
    uploads.forEach((upload) => vi.mocked(previewImport).mockReturnValueOnce(upload.promise));
    ["a.csv", "b.csv", "c.csv", "d.csv"].forEach((name) => queued(name));
    openPage();

    await waitFor(() => expect(previewImport).toHaveBeenCalledTimes(2));
    expect(screen.getAllByText("Waiting for its turn…")).toHaveLength(2);

    // one upload is over (here: it failed): the next file gets its turn
    uploads[0].reject(new Error("Could not read a.csv"));
    await waitFor(() => expect(previewImport).toHaveBeenCalledTimes(3));
    expect(await screen.findByText("Could not read a.csv")).toBeInTheDocument();
    expect(screen.getAllByText("Waiting for its turn…")).toHaveLength(1);

    uploads[1].reject(new Error("b"));
    uploads[2].reject(new Error("c"));
    await waitFor(() => expect(previewImport).toHaveBeenCalledTimes(4));
    uploads[3].reject(new Error("d")); // (leaves no turn taken for the tests after this one)
    await waitFor(() => expect(screen.queryByText("Waiting for its turn…")).not.toBeInTheDocument());
  });

  it("goes on reading them while another page is shown", async () => {
    const uploads = ["a.csv", "b.csv", "c.csv"].map((name) => ({ name, ...pending<ImportPreview>() }));
    uploads.forEach((upload) => vi.mocked(previewImport).mockReturnValueOnce(upload.promise));
    uploads.forEach((upload) => queued(upload.name));
    const { leave } = openPage();
    await waitFor(() => expect(previewImport).toHaveBeenCalledTimes(2));

    leave();
    uploads[0].resolve(preview("a.csv"));
    uploads[1].resolve(preview("b.csv"));
    await waitFor(() => expect(previewImport).toHaveBeenCalledTimes(3)); // the third got its turn
    uploads[2].resolve(preview("c.csv"));

    openPage();
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Import" })).toHaveLength(3));
    expect(previewImport).toHaveBeenCalledTimes(3); // none of them again
  });

  it("discards the upload of a file that was removed while it was read", async () => {
    const upload = pending<ImportPreview>();
    vi.mocked(previewImport).mockReturnValueOnce(upload.promise);
    queued("a.csv");
    openPage();
    await waitFor(() => expect(previewImport).toHaveBeenCalledTimes(1));

    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(discardStagedImport).not.toHaveBeenCalled(); // nothing is staged yet
    upload.resolve(preview("a.csv"));

    await waitFor(() => expect(discardStagedImport).toHaveBeenCalledWith("staged-a.csv"));
  });
});

describe("ImportFileCard: leaving the page while a file is imported", () => {
  it("shows the import when the page is opened again", async () => {
    const importing = pending<ImportCommitResult>();
    vi.mocked(commitImport).mockReturnValueOnce(importing.promise);
    queued("march.csv", { preview: preview("march.csv") });
    const { leave } = openPage();
    await userEvent.click(await screen.findByRole("button", { name: "Import" }));
    await waitFor(() => expect(commitImport).toHaveBeenCalledTimes(1));

    leave();
    importing.resolve(committed); // the answer arrives while another page is shown
    await importing.promise;

    openPage();
    expect(await screen.findByText("Imported")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Import" })).not.toBeInTheDocument();
    expect(commitImport).toHaveBeenCalledTimes(1);
  });

  it("does not import the file a second time when the page is opened again before the answer", async () => {
    const importing = pending<ImportCommitResult>();
    vi.mocked(commitImport).mockReturnValueOnce(importing.promise);
    queued("march.csv", { preview: preview("march.csv", { auto_import: true }) });
    const { leave } = openPage(true); // recognized, nothing to check: imported without asking
    await waitFor(() => expect(commitImport).toHaveBeenCalledTimes(1));

    leave();
    openPage(true);
    expect(await screen.findByText(/Importing/)).toBeInTheDocument();
    expect(commitImport).toHaveBeenCalledTimes(1);

    importing.resolve(committed);
    expect(await screen.findByText("Imported")).toBeInTheDocument();
    expect(commitImport).toHaveBeenCalledTimes(1);
  });

  it("says why the import failed when the page is opened again", async () => {
    const importing = pending<ImportCommitResult>();
    vi.mocked(commitImport).mockReturnValueOnce(importing.promise);
    queued("march.csv", { preview: preview("march.csv") });
    const { leave } = openPage();
    await userEvent.click(await screen.findByRole("button", { name: "Import" }));

    leave();
    importing.reject(new Error("This file appears to have already been imported."));
    await importing.promise.catch(() => {});

    openPage();
    expect(await screen.findByText("This file appears to have already been imported.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import" })).toBeEnabled();
  });
});

describe("ImportFileCard: the import review", () => {
  it("says inside the review why the import failed", async () => {
    vi.mocked(commitImport).mockRejectedValue(new Error("This statement is already imported (from march.pdf)."));
    queued("march.csv", { preview: toCheck("march.csv") });
    openPage();

    const review = await screen.findByRole("dialog"); // opened by itself: a kind of file not checked yet
    await userEvent.click(within(review).getByRole("button", { name: "Correct — import" }));

    // (the review fills the window: said on the card behind it, nobody would see it)
    expect(await within(review).findByRole("alert")).toHaveTextContent("This statement is already imported (from march.pdf).");
    expect(within(review).getByRole("button", { name: "Correct — import" })).toBeEnabled();
  });

  it("is open for one file at a time; the next one's opens when it is closed", async () => {
    queued("march.csv", { preview: toCheck("march.csv") });
    queued("april.csv", { preview: toCheck("april.csv") });
    openPage();

    await waitFor(() => expect(screen.getAllByRole("dialog")).toHaveLength(1));
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Check the reading: march.csv");

    await userEvent.keyboard("{Escape}"); // closes this one — not every file's
    await waitFor(() => expect(screen.getByRole("dialog")).toHaveAccessibleName("Check the reading: april.csv"));

    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // closed by the user: neither opens by itself again
    expect(screen.getAllByRole("button", { name: "Check against the original" })).toHaveLength(2);
  });
});
