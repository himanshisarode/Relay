// Thin fetch wrapper: JSON in/out, session cookie, CSRF header on writes, typed API errors.

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, any> = {},
  ) {
    super(message);
  }
}

// Empty (default): same origin, so Amplify proxies /api to the backend. Set VITE_API_BASE only when the API is
// served from its own subdomain, e.g. https://api.example.org (backend RELAY_CORS_ORIGINS must then list the app).
const API_BASE = ((import.meta.env.VITE_API_BASE as string | undefined) ?? "").replace(/\/$/, "");

/** Absolute URL for links the browser opens directly (e.g. CSV downloads). */
export const apiUrl = (path: string) => `${API_BASE}/api/v1${path}`;

let csrf = "";
export function setCsrf(token: string) {
  csrf = token;
}

function cookieCsrf() {
  return document.cookie.split("; ").find((c) => c.startsWith("relay_csrf="))?.split("=")[1] ?? "";
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = opts.method ?? (opts.body === undefined ? "GET" : "POST");
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrf || cookieCsrf();
  const res = await fetch(`${API_BASE}/api/v1${path}`, {
    method,
    headers,
    credentials: API_BASE ? "include" : "same-origin",
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? JSON.parse(text) : undefined;
  if (!res.ok) {
    const e = data?.error ?? {};
    throw new ApiError(res.status, e.code ?? "error", e.message ?? `Request failed (${res.status})`, e.details ?? {});
  }
  return data as T;
}

export const post = <T = any>(path: string, body: unknown = {}) => api<T>(path, { method: "POST", body });
export const patch = <T = any>(path: string, body: unknown) => api<T>(path, { method: "PATCH", body });
export const del = <T = any>(path: string) => api<T>(path, { method: "DELETE" });

export function qs(params: Record<string, string | number | boolean | undefined | null>) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === "validation_error" && Array.isArray(e.details.errors)) {
      return e.details.errors.map((x: any) => `${x.loc.at(-1)}: ${x.msg}`).join("; ");
    }
    return e.message;
  }
  return e instanceof Error ? e.message : "Something went wrong.";
}
