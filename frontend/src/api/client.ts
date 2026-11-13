import { getLang, translate } from "../i18n/core";

// Same origin by default: the backend serves the built frontend itself, and
// `npm run dev` proxies /api to it (vite.config.ts). A relative base keeps
// the app working no matter whether it's opened as 127.0.0.1 or localhost,
// or on a non-default port. Tests can point it at another server.
let apiBase: string = import.meta.env.VITE_API_BASE_URL || "";

export function setApiBase(base: string) {
  apiBase = base.replace(/\/$/, "");
}

export function apiUrl(path: string): string {
  return apiBase + path;
}

// Required by the backend on every state-changing request (see
// backend/app/security.py): a foreign web page can't add a custom header
// without a CORS preflight, which the backend never grants.
// Accept-Language: the backend words its messages (import warnings, errors)
// in the language chosen in the UI.
function clientHeaders(): Record<string, string> {
  return { "X-Finance-Client": "1", "Accept-Language": getLang() };
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** For the query cache: one more try when no answer came or the server
 * failed — never for a request it refused (4xx: asked again, it says the same). */
export function retryQuery(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 1;
}

interface ValidationErrorItem {
  loc?: (string | number)[];
  msg?: string;
}

// How the user knows the fields a request carries (instead of "iban", "amount_minor").
const FIELD_LABELS: Record<string, Record<string, string>> = {
  de: { iban: "IBAN", name: "Name", currency: "Währung", amount_minor: "Betrag", category: "Kategorie" },
  en: { iban: "IBAN", name: "Name", currency: "Currency", amount_minor: "Amount", category: "Category" },
};

function fieldLabel(field: string): string {
  return FIELD_LABELS[getLang()]?.[field] ?? field;
}

/** FastAPI returns `detail` as a string, or as a list of validation errors. */
export function formatErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const parts = (detail as ValidationErrorItem[]).map((item) => {
      const field = (item.loc ?? []).filter((p) => p !== "body" && p !== "query").join(".");
      const msg = (item.msg ?? translate(getLang(), "error.invalidValue")).replace(/^Value error, /, "");
      return field ? `${fieldLabel(field)}: ${msg}` : msg;
    });
    if (parts.length) return parts.join("; ");
  }
  return fallback;
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText || translate(getLang(), "error.requestFailed", { status: res.status });
    let rawDetail: unknown = undefined;
    try {
      const body = await res.json();
      rawDetail = body.detail;
      detail = formatErrorDetail(body.detail, detail);
    } catch {
      // response wasn't JSON — keep statusText
    }
    // An API route the server doesn't have: the page is newer than the
    // running program (updated, not restarted). Say what to do.
    if (res.status === 405 || (res.status === 404 && rawDetail === "Not Found")) {
      detail = translate(getLang(), "error.outdatedServer");
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

async function send(path: string, init: RequestInit = {}): Promise<Response> {
  try {
    return await fetch(apiUrl(path), { ...init, headers: { ...clientHeaders(), ...(init.headers ?? {}) } });
  } catch (error) {
    // given up on purpose (a newer search replaced this one): not an error to show
    if (init.signal?.aborted) throw error;
    // otherwise fetch only rejects when no response arrived at all (server stopped)
    throw new ApiError(0, translate(getLang(), "error.offline"));
  }
}

/** `signal`: the query cache's — it gives a request up when its answer is
 * not wanted any more (the search text changed, the page was left). */
export async function apiGet<T>(
  path: string,
  params?: Record<string, string | number | boolean | undefined>,
  signal?: AbortSignal
): Promise<T> {
  const query = new URLSearchParams();
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") {
        query.set(key, String(value));
      }
    }
  }
  const qs = query.toString();
  return handle<T>(await send(qs ? `${path}?${qs}` : path, { signal }));
}

function jsonRequest(method: string, body?: unknown): RequestInit {
  return body !== undefined
    ? { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : { method };
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return handle<T>(await send(path, jsonRequest("POST", body)));
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return handle<T>(await send(path, jsonRequest("PATCH", body)));
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  return handle<T>(await send(path, jsonRequest("PUT", body)));
}

export async function apiPostForm<T>(path: string, fields: Record<string, string>): Promise<T> {
  return handle<T>(await send(path, { method: "POST", body: new URLSearchParams(fields) }));
}

export async function apiUpload<T>(
  path: string,
  file: File,
  fields?: Record<string, string | number>
): Promise<T> {
  const formData = new FormData();
  formData.append("file", file);
  if (fields) {
    for (const [key, value] of Object.entries(fields)) {
      formData.append(key, String(value));
    }
  }
  return handle<T>(await send(path, { method: "POST", body: formData }));
}

export async function apiDelete<T>(path: string): Promise<T> {
  return handle<T>(await send(path, { method: "DELETE" }));
}
