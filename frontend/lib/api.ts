/**
 * Tiny fetch wrapper for the FastAPI backend.
 * - Sends cookies (httpOnly access/refresh tokens) with every request.
 * - Adds the CSRF header (double-submit cookie) on mutating requests.
 * - On an expired access token, refreshes once and retries.
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
    public requestId?: string,
  ) {
    super(message);
  }
}

let csrfToken: string | null = null;

export function setCsrf(token: string | null) {
  csrfToken = token;
}

function readCsrfCookie(): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(/(?:^|; )pg_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

export function getCsrf(): string | null {
  return csrfToken ?? readCsrfCookie();
}

const BASE = "/api/v1";
let refreshing: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  // Several requests may expire at once; share one refresh call.
  refreshing ??= fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    credentials: "include",
    headers: { "X-CSRF-Token": getCsrf() ?? "" },
  })
    .then(async (r) => {
      if (!r.ok) return false;
      const body = await r.json();
      setCsrf(body.csrf_token);
      return true;
    })
    .catch(() => false)
    .finally(() => setTimeout(() => (refreshing = null), 0));
  return refreshing;
}

export type Query = Record<string, string | number | boolean | null | undefined>;

export function qs(params?: Query): string {
  if (!params) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export async function api<T = unknown>(
  path: string,
  opts: { method?: string; body?: unknown; query?: Query; raw?: boolean; retry?: boolean } = {},
): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = getCsrf() ?? "";
  const res = await fetch(`${BASE}${path}${qs(opts.query)}`, {
    method,
    headers,
    credentials: "include",
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401 && opts.retry !== false && !path.startsWith("/auth/")) {
    const body = await res.clone().json().catch(() => ({}));
    if (body?.error?.code === "token_expired" && (await tryRefresh())) {
      return api<T>(path, { ...opts, retry: false });
    }
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(
      res.status,
      body?.error?.code ?? "http_error",
      body?.error?.message ?? res.statusText,
      body?.error?.details,
      body?.request_id,
    );
  }
  if (opts.raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/** Download a file (CSV/PDF) from an authenticated endpoint. */
export async function download(path: string, filename: string, query?: Query) {
  const res = await api<Response>(path, { raw: true, query });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** POST to an SSE endpoint and invoke callbacks per event (EventSource can't POST). */
export async function streamSSE(
  path: string,
  body: unknown,
  onEvent: (event: string, data: unknown) => void,
  signal?: AbortSignal,
) {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrf() ?? "" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => ({}));
    throw new ApiError(res.status, err?.error?.code ?? "http_error", err?.error?.message ?? "Stream failed");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const ev = /^event: (.*)$/m.exec(chunk)?.[1] ?? "message";
      const data = /^data: (.*)$/m.exec(chunk)?.[1];
      onEvent(ev, data ? JSON.parse(data) : null);
    }
  }
}
