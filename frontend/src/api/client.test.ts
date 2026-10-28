import { afterEach, describe, expect, it, vi } from "vitest";
import { apiPost } from "./client";

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
