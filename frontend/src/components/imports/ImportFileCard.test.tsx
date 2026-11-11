import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ImportFileCard } from "./ImportFileCard";
import { LanguageProvider } from "../../i18n/LanguageProvider";
import { listImports, removeImport } from "../../api/imports";
import { listAccounts } from "../../api/accounts";
import type { CardSnapshot } from "../../state/importQueue";
import type { ImportCommitResult, ImportRecord } from "../../types";

// The real hooks and query cache; only the requests to the backend are stubbed.
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

function renderCard(snapshot: CardSnapshot) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onSnapshot = vi.fn();
  render(
    <LanguageProvider>
      <QueryClientProvider client={queryClient}>
        <ImportFileCard
          file={new File(["date,amount"], "march.csv")}
          autoImport={false}
          snapshot={snapshot}
          onSnapshot={onSnapshot}
          onDone={() => {}}
          onRemove={() => {}}
        />
      </QueryClientProvider>
    </LanguageProvider>
  );
  return { queryClient, onSnapshot };
}

const undoButton = () => screen.getByRole("button", { name: "Undo" });

describe("ImportFileCard: undoing the import a card made", () => {
  beforeEach(() => {
    vi.mocked(listAccounts).mockResolvedValue([]);
    vi.mocked(removeImport).mockReset();
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
    renderCard({ committed });

    await waitFor(() => expect(undoButton()).toBeEnabled());
    await userEvent.click(undoButton());

    await waitFor(() => expect(removeImport).toHaveBeenCalledWith(7));
    expect(await screen.findByText(/Import undone/)).toBeInTheDocument();
  });

  it("never removes another import that has its number now", async () => {
    vi.mocked(listImports).mockResolvedValue([record(7, "march.csv")]);
    const { queryClient, onSnapshot } = renderCard({ committed });
    await waitFor(() => expect(undoButton()).toBeEnabled());

    // removed in the list — and the next import (another file) got number 7
    vi.mocked(listImports).mockResolvedValue([record(7, "april.csv")]);
    await queryClient.invalidateQueries({ queryKey: ["imports"] });

    expect(await screen.findByText(/Import undone/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
    expect(removeImport).not.toHaveBeenCalled();
    // ... also not after the page was left and opened again
    expect(onSnapshot).toHaveBeenLastCalledWith(expect.objectContaining({ committed: undefined, undone: true }));
  });

  it("forgets an import that was gone when the page was opened again", async () => {
    vi.mocked(listImports).mockResolvedValue([record(6, "february.csv")]);
    renderCard({ committed, seenInHistory: true });

    expect(await screen.findByText(/Import undone/)).toBeInTheDocument();
    expect(removeImport).not.toHaveBeenCalled();
  });

  it("offers no undo while the list doesn't show its import (yet)", async () => {
    vi.mocked(listImports).mockResolvedValue([record(6, "february.csv")]);
    renderCard({ committed });

    await waitFor(() => expect(listImports).toHaveBeenCalled());
    // just imported: the list is read again in a moment — the card stays as it is
    expect(screen.getByText("Imported")).toBeInTheDocument();
    expect(undoButton()).toBeDisabled();
    await userEvent.click(undoButton());
    expect(removeImport).not.toHaveBeenCalled();
  });
});
