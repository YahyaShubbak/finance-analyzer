import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiGet, apiPost } from "./client";
import { listTransactions } from "./transactions";

afterEach(() => vi.unstubAllGlobals());

function respond(status: number, body: unknown, statusText = "") {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body === undefined ? "" : JSON.stringify(body), { status, statusText })));
}

describe("API errors", () => {
  it("explains an outdated running program instead of 'Method Not Allowed'", async () => {
    respond(405, undefined, "Method Not Allowed");
    await expect(apiPost("/api/categories", { name: "x" })).rejects.toThrow(/older than this page/);
  });

  it("does the same for an unknown API route", async () => {
    respond(404, { detail: "Not Found" });
    await expect(apiPost("/api/categories", {})).rejects.toThrow(/restart/);
  });

  it("keeps the server's own message otherwise", async () => {
    respond(404, { detail: "Account not found" });
    await expect(apiPost("/api/accounts/9", {})).rejects.toThrow("Account not found");
  });
});

describe("a request given up on purpose", () => {
  it("is not reported as 'the app is not running'", async () => {
    const givenUp = new AbortController();
    const fetched = vi.fn(async (_url: string, init?: RequestInit) => {
      init?.signal?.throwIfAborted();
      return new Response("{}");
    });
    vi.stubGlobal("fetch", fetched);
    givenUp.abort();

    const outcome = await apiGet("/api/transactions", { search: "rew" }, givenUp.signal).catch((error: unknown) => error);

    expect(outcome).not.toBeInstanceOf(ApiError);
    expect((outcome as Error).name).toBe("AbortError");
  });

  it("the list of transactions passes the query cache's signal on", async () => {
    const fetched = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({ items: [], total: 0 })));
    vi.stubGlobal("fetch", fetched);
    const controller = new AbortController();

    await listTransactions({ search: "rewe" }, controller.signal);

    expect(fetched.mock.calls[0][1]?.signal).toBe(controller.signal);
  });
});
