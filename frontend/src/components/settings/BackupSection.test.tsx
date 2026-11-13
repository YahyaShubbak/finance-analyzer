import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BackupSection } from "./BackupSection";
import { LanguageProvider } from "../../i18n/LanguageProvider";
import { deleteBackup, listBackups } from "../../api/backup";

// The real section and hooks; only the requests to the backend are stubbed.
vi.mock("../../api/backup", async (original) => ({
  ...(await original<typeof import("../../api/backup")>()),
  listBackups: vi.fn(),
  deleteBackup: vi.fn(),
}));

const backup = (filename: string) => ({
  filename, created_at: "2026-03-01T10:00:00+00:00", size_bytes: 2048, counts: { accounts: 1, transactions: 3, imports: 1 },
});

describe("BackupSection", () => {
  it("deletes a backup only after asking", async () => {
    vi.mocked(listBackups).mockResolvedValue([backup("finance-backup-old.zip"), backup("finance-backup-new.zip")]);
    vi.mocked(deleteBackup).mockResolvedValue(undefined);
    render(
      <LanguageProvider>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <BackupSection />
        </QueryClientProvider>
      </LanguageProvider>
    );

    await userEvent.click((await screen.findAllByRole("button", { name: "Delete" }))[0]);
    expect(deleteBackup).not.toHaveBeenCalled();
    expect(screen.getByText(/Delete the backup finance-backup-old.zip\?/)).toBeInTheDocument();

    vi.mocked(listBackups).mockResolvedValue([backup("finance-backup-new.zip")]);
    await userEvent.click(screen.getByRole("button", { name: "Yes, delete it" }));

    await waitFor(() => expect(deleteBackup).toHaveBeenCalledWith("finance-backup-old.zip"));
    // the list is read again: the backup is gone from it
    await waitFor(() => expect(screen.queryByText(/finance-backup-old/)).not.toBeInTheDocument());
  });
});
