/**
 * Typed HTTP client generated from the backend OpenAPI 3.1 schema (see `npm run gen:api`).
 * Access token lives in memory only; the refresh token is an httpOnly cookie set by the API.
 */
import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";

/** Origin of the API ("" = same origin, nginx/vite proxy /api). Schema paths already contain /api/v1. */
export const API_ORIGIN = (import.meta.env.VITE_API_ORIGIN as string | undefined) ?? "";
export const API_BASE = `${API_ORIGIN}/api/v1`;

export interface Problem {
  type: string;
  title: string;
  status: number;
  details?: unknown;
  detail?: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  constructor(status: number, problem: Partial<Problem>) {
    super(problem.title ?? describeValidation(problem.detail) ?? `HTTP ${status}`);
    this.status = status;
    this.code = problem.type ?? "error";
    this.details = problem.details ?? problem.detail;
  }
}

function describeValidation(detail: unknown): string | undefined {
  if (!Array.isArray(detail)) return typeof detail === "string" ? detail : undefined;
  return detail
    .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg ?? ""}`)
    .join("; ");
}

let accessToken: string | null = null;
let refreshPromise: Promise<boolean> | null = null;
let onUnauthorized: (() => void) | null = null;

export const tokenStore = {
  get: () => accessToken,
  set: (t: string | null) => {
    accessToken = t;
  },
  onUnauthorized: (cb: () => void) => {
    onUnauthorized = cb;
  },
};

async function refreshAccessToken(): Promise<boolean> {
  refreshPromise ??= fetch(`${API_BASE}/auth/refresh`, { method: "POST", credentials: "include" })
    .then(async (r) => {
      if (!r.ok) return false;
      const body = (await r.json()) as { access_token: string };
      accessToken = body.access_token;
      return true;
    })
    .catch(() => false)
    .finally(() => {
      refreshPromise = null;
    });
  return refreshPromise;
}

/** fetch wrapper: injects bearer token, retries once after a silent refresh on 401. */
export async function authFetch(input: Request): Promise<Response> {
  const attempt = (req: Request) => {
    const r = req.clone();
    if (accessToken) r.headers.set("Authorization", `Bearer ${accessToken}`);
    return fetch(r, { credentials: "include" });
  };
  let res = await attempt(input);
  const isAuthCall = /^\/api\/v1\/auth\/(login|refresh|logout|mfa)/.test(
    new URL(input.url, window.location.origin).pathname,
  );
  if (res.status === 401 && !isAuthCall) {
    if (await refreshAccessToken()) res = await attempt(input);
    else onUnauthorized?.();
  }
  return res;
}

const throwOnError: Middleware = {
  async onResponse({ response }) {
    if (response.ok) return undefined;
    let problem: Partial<Problem> = {};
    try {
      problem = (await response.clone().json()) as Problem;
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(response.status, problem);
  },
};

export const api = createClient<paths>({ baseUrl: API_ORIGIN || window.location.origin, fetch: authFetch });
api.use(throwOnError);

/** Unwraps openapi-fetch result (errors are already thrown by middleware). */
export function unwrap<T>(res: { data?: T; error?: unknown }): T {
  return res.data as T;
}
