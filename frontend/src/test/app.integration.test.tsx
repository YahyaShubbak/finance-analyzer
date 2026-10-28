/**
 * OPT-IN integration test against a REAL backend.
 *
 * It creates accounts and imports data, so it must never run against the
 * database you actually use. It is skipped unless E2E_API_BASE is set:
 *
 *   cd backend && FINANCE_DATA_DIR=$(mktemp -d) .venv/bin/python -m app --port 8421
 *   cd frontend && E2E_API_BASE=http://127.0.0.1:8421 npm test
 *
 * "Browser-level" verification substitute.
 *
 * A real Chromium binary could not be downloaded in this sandbox
 * (cdn.playwright.dev is not in the network egress allowlist, and the
 * only system package available — `chromium-browser` via apt — requires
 * snap, which is also unavailable). This is a genuine environment
 * limitation, documented here rather than worked around silently.
 *
 * As the closest available substitute, this test renders the REAL React
 * component tree (App, AppShell, all pages) using React Testing Library +
 * jsdom, and makes REAL network requests (via Node's native fetch) to the
 * REAL FastAPI backend running on 127.0.0.1:8420 — no mocked responses.
 * This verifies actual routing, actual state updates, actual API
 * integration, and actual localStorage persistence.
 *
 * What this does NOT verify, and where real Playwright/browser tests
 * remain necessary before considering V1 fully done:
 *   - Visual/CSS rendering, layout, responsiveness
 *   - True OS-level drag-and-drop (jsdom has no drag/drop implementation —
 *     this test uses the file-input `change` event instead, which is the
 *     DropZone component's own documented fallback for "click to browse")
 *   - Cross-browser behavior
 *
 * Prerequisite: the real backend must already be running on
 * 127.0.0.1:8420 with an empty-ish or known DB state before this file
 * runs (it creates its own uniquely-named account/data to stay
 * independent of whatever else is in the DB).
 */
import { describe, it, expect, beforeAll, vi } from "vitest";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "../App";
import { setApiBase } from "../api/client";
import { LanguageProvider } from "../i18n/LanguageProvider";

const env = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env ?? {};
const API_BASE = env.E2E_API_BASE ?? "";
const CLIENT_HEADER = { "X-Finance-Client": "1" };
const RUN_ID = Date.now();
const ACCOUNT_NAME = `E2E Test Account ${RUN_ID}`;

function renderApp(initialPath = "/") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <LanguageProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[initialPath]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>
    </LanguageProvider>
  );
}

function csvFile(name: string, rows: string[]) {
  const content = ["Date,Description,Amount", ...rows].join("\n");
  return new File([content], name, { type: "text/csv" });
}

/**
 * Manually builds a multipart/form-data body as a plain string, bypassing
 * the browser FormData/File classes entirely. Needed because jsdom's File
 * (which extends its own internal Blob shadow) isn't recognized by Node's
 * real fetch/undici when building multipart bodies from a FormData — the
 * request hangs indefinitely (see the skipped test below for details).
 * This lets beforeAll seed real data via the real API without hitting that
 * same interop issue, so the read-only tests below aren't blocked by it.
 */
async function postMultipartCsv(url: string, filename: string, csvContent: string, accountId: number) {
  const boundary = `----vitest${Date.now()}`;
  const body =
    `--${boundary}\r\n` +
    `Content-Disposition: form-data; name="file"; filename="${filename}"\r\n` +
    `Content-Type: text/csv\r\n\r\n` +
    `${csvContent}\r\n` +
    `--${boundary}\r\n` +
    `Content-Disposition: form-data; name="account_id"\r\n\r\n` +
    `${accountId}\r\n` +
    `--${boundary}--\r\n`;

  return fetch(url, {
    method: "POST",
    headers: { ...CLIENT_HEADER, "Content-Type": `multipart/form-data; boundary=${boundary}` },
    body,
  });
}

let seededAccountId: number;

beforeAll(async () => {
  if (!API_BASE) return;
  setApiBase(API_BASE);
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Backend is not running on ${API_BASE} — start it before running this test.`);

  // Create a dedicated account so this test's data is independent of
  // whatever else already exists in the (real, persistent) database.
  const accountRes = await fetch(`${API_BASE}/api/accounts`, {
    method: "POST",
    headers: { ...CLIENT_HEADER, "Content-Type": "application/json" },
    body: JSON.stringify({ name: ACCOUNT_NAME, account_type: "checking", currency: "EUR" }),
  });
  const account = await accountRes.json();
  seededAccountId = account.id;

  // Seed real transactions via the real API (bypassing the browser
  // File/FormData path — see postMultipartCsv doc comment) so the
  // read-only tests (filtering, pagination, dashboard) have real data to
  // work with independent of the upload-flow test below.
  const csvContent =
    "Date,Description,Amount\n" +
    `2026-06-01,E2E Grocery Run ${RUN_ID},-41.30\n` +
    `2026-06-05,E2E Salary ${RUN_ID},2500.00\n`;
  const previewRes = await postMultipartCsv(
    `${API_BASE}/api/imports/preview`, `seed_${RUN_ID}.csv`, csvContent, seededAccountId
  );
  if (!previewRes.ok) {
    throw new Error(`Seed preview failed: ${previewRes.status} ${await previewRes.text()}`);
  }
  const preview = await previewRes.json();
  const commitRes = await fetch(`${API_BASE}/api/imports/commit`, {
    method: "POST",
    headers: { ...CLIENT_HEADER, "Content-Type": "application/json" },
    body: JSON.stringify({ staging_id: preview.staging_id, account_id: seededAccountId }),
  });
  if (!commitRes.ok) {
    throw new Error(`Seed commit failed: ${commitRes.status} ${await commitRes.text()}`);
  }
  const commitJson = await commitRes.json();
  if (commitJson.transactions_created !== 2) {
    throw new Error(`Seed commit created unexpected count: ${JSON.stringify(commitJson)}`);
  }
});

describe.skipIf(!API_BASE)("Real app against a real (throwaway) backend", () => {
  it("Dashboard opens successfully", async () => {
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("sidebar navigation moves between pages", async () => {
    const user = userEvent.setup();
    renderApp("/");
    await screen.findByRole("heading", { name: "Dashboard" });

    await user.click(screen.getByRole("link", { name: /Transactions/i }));
    expect(await screen.findByRole("heading", { name: "Transactions" })).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: /Imports/i }));
    expect(await screen.findByRole("heading", { name: "Imports" })).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: /^Dashboard$/i }));
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it.skip(
    "CSV can be selected (file-input fallback for drag & drop), previewed, and committed " +
      "— SKIPPED: jsdom's File class extends its own Blob shadow, which Node's real " +
      "fetch/undici does not recognize when building multipart bodies, so the upload " +
      "request hangs indefinitely. Confirmed as a jsdom↔fetch interop limitation, not an " +
      "app bug: the identical request completes in ~50ms via a plain Node script and via " +
      "curl against this same running backend (see verification report). This is exactly " +
      "the kind of gap a real browser wouldn't have, and is the strongest argument for " +
      "running the real Playwright suite once network access allows a browser download.",
    async () => {
    const user = userEvent.setup();
    renderApp("/imports");
    await screen.findByRole("heading", { name: "Imports" });

    const file = csvFile(`e2e_${RUN_ID}.csv`, [
      `2026-06-01,E2E Grocery Run ${RUN_ID},-41.30`,
      `2026-06-05,E2E Salary ${RUN_ID},2500.00`,
    ]);

    // DropZone's hidden <input type="file"> is the documented click-to-browse
    // fallback; jsdom cannot simulate real OS drag-and-drop events.
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).toBeTruthy();
    await user.upload(fileInput, file);

    // Preview should appear with real parsed data from the real backend.
    await waitFor(() => expect(screen.getByText(/2 transactions/)).toBeInTheDocument(), { timeout: 5000 });
    expect(screen.getByText(new RegExp(`E2E Grocery Run ${RUN_ID}`))).toBeInTheDocument();

    // Select our dedicated test account, then confirm the import.
    const select = screen.getByRole("combobox", { name: "Target account" }) as HTMLSelectElement;
    await user.selectOptions(select, ACCOUNT_NAME);

    const confirmButton = screen.getByRole("button", { name: /^Import$/ });
    await user.click(confirmButton);

    await waitFor(
      () => expect(screen.getByText(/Imported 2 transactions/)).toBeInTheDocument(),
      { timeout: 5000 }
    );

    // Import history should now list this file.
    await waitFor(() => expect(screen.getByText(`e2e_${RUN_ID}.csv`)).toBeInTheDocument());
  });

  it("imported transactions appear on the Transactions page, and filtering/pagination work against real data", async () => {
    const user = userEvent.setup();
    renderApp("/transactions");
    await screen.findByRole("heading", { name: "Transactions" });

    // Isolate to our dedicated test account via the account filter — more
    // reliable than matching on displayed text, since the merchant
    // normalizer intentionally strips long numeric reference IDs (like our
    // RUN_ID) from what's *displayed*, even though the backend still
    // searches/stores the full original description.
    const accountFilterSelect = screen.getByRole("combobox", { name: "Account" }) as HTMLSelectElement;
    await waitFor(() => expect(within(accountFilterSelect).getByText(ACCOUNT_NAME)).toBeInTheDocument(), {
      timeout: 5000,
    });
    await user.selectOptions(accountFilterSelect, ACCOUNT_NAME);

    // all three at once: the unfiltered list stays visible (placeholder data)
    // until the filtered one has loaded
    await waitFor(() => {
      expect(screen.getByText("E2E Grocery Run")).toBeInTheDocument();
      expect(screen.getByText("E2E Salary")).toBeInTheDocument();
      expect(screen.getByText(/^2 transactions?$/)).toBeInTheDocument();
    }, { timeout: 5000 });

    // Filtering: search box narrows results via a real API call against
    // the full original description (unaffected by display-side stripping).
    const searchBox = screen.getByPlaceholderText(/Search description/i);
    await user.type(searchBox, `E2E Salary ${RUN_ID}`);

    await waitFor(() => {
      expect(screen.queryByText("E2E Grocery Run")).not.toBeInTheDocument();
      expect(screen.getByText("E2E Salary")).toBeInTheDocument();
      expect(screen.getByText(/^1 transaction$/)).toBeInTheDocument();
    });

    await user.clear(searchBox);
    await waitFor(() => {
      expect(screen.getByText("E2E Grocery Run")).toBeInTheDocument();
      expect(screen.getByText(/^2 transactions?$/)).toBeInTheDocument();
    });

    // Pagination controls are present and reflect real total counts.
    expect(screen.getByText(/Page 1 of/)).toBeInTheDocument();
  });

  it("Dashboard totals and charts render from real API data", async () => {
    const user = userEvent.setup();
    renderApp("/");
    await screen.findByRole("heading", { name: "Dashboard" });
    // The dashboard has its own period selector (default: this month);
    // the seeded data is from June 2026.
    await user.click(screen.getByRole("button", { name: "All time" }));

    await waitFor(() => expect(screen.getByText("Income")).toBeInTheDocument());
    expect(screen.getByText("Expenses")).toBeInTheDocument();
    expect(screen.getByText("Net cash flow")).toBeInTheDocument();

    // Recharts renders its responsive container and feeds it real data;
    // full SVG painting requires real layout (ResizeObserver/getBoundingClientRect),
    // which jsdom doesn't implement — verified structurally instead.
    await waitFor(
      () => expect(document.querySelectorAll(".recharts-responsive-container").length).toBeGreaterThan(0),
      { timeout: 5000 }
    );
  });

  it("persisted filters survive an app remount (page-reload equivalent)", async () => {
    const user = userEvent.setup();
    const { unmount } = renderApp("/transactions");
    await screen.findByRole("heading", { name: "Transactions" });

    const searchBox = screen.getByPlaceholderText(/Search description/i);
    await user.type(searchBox, `PERSIST_${RUN_ID}`);
    await waitFor(() => expect(searchBox).toHaveValue(`PERSIST_${RUN_ID}`));

    // Verify the actual persistence mechanism directly: the value must be
    // in localStorage itself, not just in in-memory component state — this
    // is what a real page reload would read from.
    const stored = JSON.parse(localStorage.getItem("finance.filters.v1") ?? "{}");
    expect(stored.search).toBe(`PERSIST_${RUN_ID}`);

    // Unmounting React and clearing the module registry, then re-importing
    // App fresh, is the closest jsdom equivalent to a real page reload —
    // a plain unmount/remount would still share the same in-memory JS
    // module singleton, which wouldn't actually prove localStorage (rather
    // than live JS state) is what's carrying the value across reloads.
    unmount();
    vi.resetModules();
    const { default: FreshApp } = await import("../App");
    // the fresh modules have their own i18n context
    const { LanguageProvider: FreshLanguageProvider } = await import("../i18n/LanguageProvider");
    (await import("../api/client")).setApiBase(API_BASE);

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <FreshLanguageProvider>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/transactions"]}>
            <FreshApp />
          </MemoryRouter>
        </QueryClientProvider>
      </FreshLanguageProvider>
    );

    await screen.findByRole("heading", { name: "Transactions" });
    const searchBoxAfterReload = await screen.findByPlaceholderText(/Search description/i);
    expect(searchBoxAfterReload).toHaveValue(`PERSIST_${RUN_ID}`);

    // Clean up so this doesn't leak into other tests/manual verification.
    await user.clear(searchBoxAfterReload);
  });
});
