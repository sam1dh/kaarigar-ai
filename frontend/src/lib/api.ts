/** Typed fetch wrapper around the FastAPI backend.
 * - Prefixes every path with VITE_API_URL ("/api" in dev, proxied to :8000).
 * - Adds Authorization: Bearer <supabase access token>.
 * - Throws ApiError built from the {"error": {code, message}} envelope.
 */
import { supabase } from "./supabase";

const BASE = (import.meta.env.VITE_API_URL as string) || "/api";

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export interface ApiOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

export async function api<T = unknown>(
  path: string,
  options: ApiOptions = {},
): Promise<T> {
  const token = (await supabase.auth.getSession()).data.session?.access_token;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });

  if (!res.ok) {
    let code = "request_failed";
    let message = "Something went wrong. Please try again.";
    try {
      const data = await res.json();
      if (data?.error?.code) code = data.error.code;
      if (data?.error?.message) message = data.error.message;
    } catch {
      /* non-JSON error body (e.g. proxy 500 when the backend is down) */
    }
    // 5xx means the service itself failed — never tell the user their
    // credentials were wrong (test case PL-09). Keep a specific backend code
    // such as `llm_failed` or `stt_failed` so the screen can show the friendly
    // "AI helper is busy" message; only fall back when no code was returned.
    if (res.status >= 500 && code === "request_failed") {
      code = "server_error";
      message = "Can't reach the service. Please try again.";
    }
    // Deactivated by a supervisor while holding a still-valid token: sign out at
    // once and show the reason on the login screen (same as profile_missing).
    if (res.status === 403 && code === "deactivated") {
      try {
        sessionStorage.setItem("kaarigar.authNotice", message);
      } catch {
        /* storage blocked */
      }
      await supabase.auth.signOut();
      const target = window.location.pathname.startsWith("/manager")
        ? "/manager/login"
        : "/login";
      if (!window.location.pathname.endsWith("/login")) {
        window.location.assign(target);
      }
    }
    throw new ApiError(res.status, code, message);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
