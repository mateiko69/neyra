/**
 * Central JSON client: dedupe, per-route throttle, short GET cache, shared across pages.
 * CORS preflight (OPTIONS) is issued by the browser per origin/method/header combo — fewer
 * parallel identical requests mean fewer duplicate preflights; we do not send OPTIONS from here.
 */
import { API_URL as resolvedApiUrl } from "./apiBase";
import { formatApiError } from "./apiErrorFormat";
import { getAuthBootstrapResult, invalidateAuthBootstrapCache, type AuthBootstrapResult } from "./auth/bootstrap";
import { dispatchAuthExpired } from "./auth/navigation";
import {
  clearStoredSession,
  getStoredToken,
  hasValidTokenShape,
  setStoredToken,
} from "./auth/session";
import { invalidateMyProfileAvatarCache } from "./meProfileCache";
import { clearMatchesNewBadgeDismissals } from "./matchesNewBadge";
import { clearNavBadgesStore } from "./navBadgesStore";

export const API_URL = resolvedApiUrl;

export {
  getBackendPublicUrl,
  resolveMediaUrl,
  PRIMARY_IMAGE_PLACEHOLDER,
  primaryPhotoFromList,
} from "./media";

/**
 * Message when no HTTP response was received (connection failed, CORS, DNS, etc.).
 * Do not use this for 401/429 or other status codes — only pre-response failures.
 */
export function formatUnreachableError(apiUrl: string = API_URL): string {
  return `API unreachable (${apiUrl}). Check your connection and that the server is running.`;
}

/** @deprecated Prefer {@link formatUnreachableError} for new code. */
export function formatNetworkError(error: unknown, apiUrl: string = API_URL): string {
  if (error instanceof Error && (error.name === "AbortError" || error.name === "ApiRequestAbortedError")) {
    return "";
  }
  if (typeof error === "object" && error !== null && "name" in error && (error as { name: string }).name === "AbortError") {
    return "";
  }
  if (error instanceof TypeError) {
    return formatUnreachableError(apiUrl);
  }
  if (error instanceof Error) return error.message;
  return formatUnreachableError(apiUrl);
}

function isAbortError(e: unknown): boolean {
  if (e instanceof Error && e.name === "AbortError") return true;
  if (typeof e === "object" && e !== null && "name" in e && (e as { name: string }).name === "AbortError") {
    return true;
  }
  return false;
}

/** Request was aborted (e.g. AbortSignal); not a server error or outage. */
export class ApiRequestAbortedError extends Error {
  constructor(cause?: unknown) {
    super("Request aborted");
    this.name = "ApiRequestAbortedError";
    if (cause instanceof Error && cause.stack) {
      this.stack = `${this.stack}\nCaused by: ${cause.stack}`;
    }
  }
}

/** True when the request was cancelled (AbortSignal); do not treat as outage or 401. */
export function isRequestAborted(e: unknown): boolean {
  if (e instanceof ApiRequestAbortedError) return true;
  return isAbortError(e);
}

export { formatApiError };

/** Canonical session token key (localStorage). Legacy keys are still read for migration. */
export { TOKEN_STORAGE_KEY } from "./auth/session";

/**
 * Bump when the server invalidates all sessions (e.g. DB wiped). Clients storing an older
 * `neyra:auth_storage_version` clear tokens + session storage on next load.
 */
export const AUTH_STORAGE_VERSION = 1;

const AUTH_VERSION_STORAGE_KEY = "neyra:auth_storage_version" as const;

let authStorageVersionMigrationDone = false;

export function getToken(): string {
  return getStoredToken();
}

export function setAccessToken(token: string) {
  if (typeof window === "undefined") return;
  invalidateAuthBootstrapCache();
  authHydrated = true;
  authState = "authorized";
  authRedirectIssued = false;
  invalidateApiGetCache();
  invalidateMyProfileAvatarCache();
  setStoredToken(token);
  void getAuthBootstrapResult({ force: true }).then(applyAuthBootstrapResult);
}

/**
 * Client auth for API guarding and polling.
 * - unknown: not hydrated yet (treat as blocking-unknown only after hydrate runs)
 * - unauthorized: no session or session ended (401); protected calls must not hit the network
 * - authorized: logged-in session active
 */
export type AuthState = "unknown" | "authorized" | "unauthorized";

let authState: AuthState = "unknown";
let authHydrated = false;
/** After first 401 redirect, avoid replace("/login") storms. */
let authRedirectIssued = false;

/** Dispatched when session becomes unauthorized (401 or logout) so pollers clear intervals. */
export const AUTH_UNAUTHORIZED_EVENT = "neyra:auth-unauthorized";

export function getAuthState(): AuthState {
  return authState;
}

function dispatchAuthUnauthorized(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT));
}

/**
 * Call once per browser session on first API use; derives state from storage.
 * No token → unauthorized; token → unknown until first successful protected response promotes to authorized.
 */
export function hydrateAuthStateFromStorage(): void {
  if (typeof window === "undefined") return;
  applyAuthStorageVersionMigration();
  if (authHydrated) return;
  authHydrated = true;
  const t = getStoredToken();
  if (t && !hasValidTokenShape(t)) {
    clearStoredSession();
    authState = "unauthorized";
    return;
  }
  // One GET /auth/me on boot decides cookie vs bearer session.
  authState = "unknown";
}

/**
 * Applies GET /auth/me bootstrap result to in-memory API auth flags (no fetch).
 */
export function applyAuthBootstrapResult(r: AuthBootstrapResult): void {
  if (typeof window === "undefined") return;
  if (r.status === "ok") {
    authHydrated = true;
    authState = "authorized";
    authRedirectIssued = false;
  } else if (r.status === "unauthorized") {
    // Keep bootstrap lastResult so we do not refetch /auth/me in a tight loop after boot 401.
    clearAuth({ invalidateBootstrap: false });
  }
}

/**
 * Session validation: shares the same single-flight GET /auth/me as app boot.
 */
export function ensureAuthBootstrapped(): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  hydrateAuthStateFromStorage();
  if (authState !== "unknown") return Promise.resolve();
  return getAuthBootstrapResult().then(applyAuthBootstrapResult);
}

/** @deprecated Prefer {@link getAuthState} === "unauthorized" after hydrate. */
export function isAuthSessionTerminated(): boolean {
  if (typeof window === "undefined") return false;
  hydrateAuthStateFromStorage();
  return authState === "unauthorized";
}

function normalizeApiPath(path: string): string {
  return path.split("?")[0] || path;
}

/** Endpoints that must be reachable without a session (login, signup, public config). */
export function isPublicApiPath(path: string, method: string): boolean {
  const m = method.toUpperCase();
  const p = normalizeApiPath(path);
  if (m === "POST" && (p === "/auth/login" || p === "/auth/register" || p === "/auth/verify-email")) return true;
  if (m === "POST" && p === "/account/restore") return true;
  if (m === "GET" && p.startsWith("/auth/social/providers")) return true;
  return false;
}

export function clearAuth(opts?: { invalidateBootstrap?: boolean }) {
  if (typeof window === "undefined") return;
  if (opts?.invalidateBootstrap !== false) {
    invalidateAuthBootstrapCache();
  }
  authHydrated = true;
  authState = "unauthorized";
  clearStoredSession();
  invalidateApiGetCache();
  invalidateMyProfileAvatarCache();
  clearMatchesNewBadgeDismissals();
  clearNavBadgesStore("clear-auth");
  dispatchAuthUnauthorized();
}

function applyAuthStorageVersionMigration(): void {
  if (typeof window === "undefined" || authStorageVersionMigrationDone) return;
  authStorageVersionMigrationDone = true;
  try {
    const prev = localStorage.getItem(AUTH_VERSION_STORAGE_KEY);
    if (prev != null && prev !== String(AUTH_STORAGE_VERSION)) {
      clearAuth();
    }
    localStorage.setItem(AUTH_VERSION_STORAGE_KEY, String(AUTH_STORAGE_VERSION));
  } catch {
    /* ignore quota / private mode */
  }
}

export type ApiFetchOptions = RequestInit & {
  /** When true, a 401 will not clear the session or redirect (e.g. login form). */
  skipAuthRedirect?: boolean;
  /** Dev: why this request was made (loops / throttles). */
  metaReason?: string;
  /** When true, do not apply per-path minimum gap (initial load, manual refresh). `/nav/badges` always honors its cooldown. */
  skipThrottle?: boolean;
  /** When true, bypass GET response cache (writes, pull-to-refresh). */
  skipCache?: boolean;
  /**
   * When true, a total network failure (no HTTP response) resolves to `undefined` instead of throwing.
   * Use for non-critical pollers (nav badges, ws token) so the UI does not surface hard failures.
   */
  softFail?: boolean;
};

const LOG_API =
  typeof process !== "undefined" &&
  (process.env.NODE_ENV === "development" || process.env.NEXT_PUBLIC_DEBUG_API === "1");

const DEBUG_API_HOT = typeof process !== "undefined" && process.env.NEXT_PUBLIC_DEBUG_API === "1";

const LOG_AUTH = LOG_API || DEBUG_API_HOT;

function logAuthRequestContext(phase: string, path: string, method: string, metaReason?: string) {
  if (!LOG_AUTH) return;
  const tok = getToken();
  console.debug(`[neyra-auth] ${phase}`, {
    path,
    method,
    metaReason: metaReason ?? "",
    bearerPresent: Boolean(tok),
    bearerLen: tok ? tok.length : 0,
  });
}

function logAuthUnauthorizedResponse(path: string, method: string, metaReason?: string) {
  if (!LOG_AUTH) return;
  console.warn("[neyra-auth] 401 Unauthorized (session cleared, redirect if applicable)", {
    path,
    method,
    metaReason: metaReason ?? "",
  });
}

/** Dev-only: total completed request attempts logged (not cache hits that return early). */
const endpointRequestTotals = new Map<string, number>();

/** Dev: snapshot of GET/POST counts per path (normalized, no query). */
export function peekApiRequestTotalsForDebug(): Record<string, number> {
  return Object.fromEntries(endpointRequestTotals);
}

/** Dev / NEXT_PUBLIC_DEBUG_API: trace request frequency (watch for loops). */
export function logApiCall(path: string, method: string = "GET", metaReason?: string) {
  if (LOG_API) {
    const k = `${method.toUpperCase()}:${normalizeApiPath(path)}`;
    endpointRequestTotals.set(k, (endpointRequestTotals.get(k) ?? 0) + 1);
  }
  recordApiBurst(path, method, metaReason);
  if (!LOG_API) return;
  if (metaReason) console.log("API CALL:", path, method, `(${metaReason})`);
  else console.log("API CALL:", path, method);
  if (DEBUG_API_HOT) {
    const hot =
      path === "/nav/badges" ||
      /^\/messages\//.test(path) ||
      path.startsWith("/analytics/track") ||
      path.startsWith("/daily/");
    if (hot) console.debug("[neyra][api-hot]", method, path, metaReason ?? "");
  }
}

/** Detect hot loops: same endpoint >5 times in 2s. Dev only. */
const apiBurstWindowMs = 2_000;
const apiBurstLimit = 5;
const apiBurstBuckets = new Map<string, number[]>();

function recordApiBurst(path: string, method: string, metaReason?: string) {
  const key = `${method.toUpperCase()}:${path}`;
  const now = Date.now();
  const bucket = apiBurstBuckets.get(key) ?? [];
  const next = bucket.filter((t) => now - t < apiBurstWindowMs);
  next.push(now);
  apiBurstBuckets.set(key, next);
  if (next.length > apiBurstLimit) {
    console.warn("[neyra] API burst detected", {
      key,
      count: next.length,
      windowMs: apiBurstWindowMs,
      metaReason,
    });
  }
}

/** Skip poll when apiFetch throttles duplicate GETs (caller may ignore). */
export class ApiThrottleSkipError extends Error {
  constructor(readonly path: string, readonly metaReason?: string) {
    super("THROTTLE_SKIP");
    this.name = "ApiThrottleSkipError";
  }
}

/** HTTP 429 — not a network outage; message is "Rate limited" (optional server detail). */
export class RateLimitError extends Error {
  constructor(
    readonly path: string,
    readonly status: number,
    message: string = "Rate limited",
  ) {
    super(message);
    this.name = "RateLimitError";
  }
}

/** HTTP 402 — show paywall / subscription UX. */
export class ApiPaywallError extends Error {
  constructor(
    readonly path: string,
    readonly status: number,
    message: string = "Payment required",
  ) {
    super(message);
    this.name = "ApiPaywallError";
  }
}

/** @deprecated Prefer {@link RateLimitError}. */
export const ApiRateLimitError = RateLimitError;

/** HTTP 401 — use message "Unauthorized" for stable UI handling. */
export class ApiUnauthorizedError extends Error {
  constructor(readonly path: string) {
    super("Unauthorized");
    this.name = "ApiUnauthorizedError";
  }
}

const inflightDedupe = new Map<string, Promise<unknown>>();
const throttleLastDoneAt = new Map<string, number>();
const rateLimitBackoffUntil = new Map<string, number>();

type GetCacheEntry = { expiresAt: number; payload: unknown };
const getResponseCache = new Map<string, GetCacheEntry>();
const RATE_LIMIT_BACKOFF_MS = 4_000;
const TRANSIENT_NETWORK_RETRIES = 2;
const UNREACHABLE_LOG_COOLDOWN_MS = 60_000;
const unreachableLastLoggedAt = new Map<string, number>();

function logUnreachableThrottled(pathKey: string, detail: Record<string, unknown>): void {
  const errRaw = String(detail["error"] ?? "");
  if (/abort/i.test(errRaw) || errRaw.includes("Request aborted")) return;
  const now = Date.now();
  const prev = unreachableLastLoggedAt.get(pathKey) ?? 0;
  if (now - prev < UNREACHABLE_LOG_COOLDOWN_MS) return;
  unreachableLastLoggedAt.set(pathKey, now);
  const msg = String(detail["error"] ?? detail["phase"] ?? "");
  if (LOG_API || (typeof process !== "undefined" && process.env.NODE_ENV === "development")) {
    console.warn("[neyra] API unreachable (throttled)", { path: pathKey, ...detail });
  } else if (msg && !pathKey.includes("/nav/badges") && !pathKey.includes("/ws/token")) {
    console.warn("[neyra] API unreachable", { path: pathKey });
  }
}

function parseRetryAfterMs(value: string | null): number | null {
  if (!value) return null;
  const v = value.trim();
  if (!v) return null;
  // Retry-After: seconds or HTTP-date
  const asSeconds = Number(v);
  if (Number.isFinite(asSeconds) && asSeconds >= 0) {
    return Math.min(120_000, Math.max(0, Math.trunc(asSeconds * 1000)));
  }
  const asDate = Date.parse(v);
  if (Number.isFinite(asDate)) {
    const delta = asDate - Date.now();
    return Math.min(120_000, Math.max(0, Math.trunc(delta)));
  }
  return null;
}

function sleepMs(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function authCacheSegment(): string {
  const t = getToken();
  if (!t) return "anon";
  return `t${t.length}:${t.slice(-16)}`;
}

function getCacheKey(path: string, method: string): string | null {
  if (method !== "GET" && method !== "HEAD") return null;
  return `${authCacheSegment()}:${path}`;
}

function getGetCacheTtlMs(path: string): number {
  // Product rule: cache GETs 5–10 seconds (snappy, but collapses bursts).
  // Per-route overrides must still stay within this window.
  if (path === "/nav/badges") return 10_000;
  if (path === "/matches") return 10_000;
  if (path === "/likes/received") return 10_000;
  if (path === "/messages/conversations") return 10_000;
  if (path === "/discover/feed") return 10_000;
  if (path === "/auth/me") return 10_000;
  if (path === "/profiles/me") return 45_000;
  if (path === "/profiles/me/risk") return 10_000;
  if (path === "/subscriptions/me") return 10_000;
  if (path === "/daily/boosts") return 10_000;
  if (path.startsWith("/auth/social/providers")) return 10_000;
  if (path.startsWith("/profile/trust")) return 10_000;
  /** Short cache collapses duplicate thread GETs (poll + Strict Mode) without hiding fresh sends (skipCache on write paths). */
  if (/^\/messages\/\d+$/.test(path)) return 10_000;
  return 8_000;
}

/** Minimum ms between completed GET attempts for the same path (reduces bursts → 429). */
const GLOBAL_GET_COOLDOWN_MS = 5_000;

function throttleGapMs(path: string, method: string): number {
  if (method !== "GET") return 0;
  if (path === "/nav/badges") return 15_000;
  if (path === "/matches") return 8_000;
  if (path === "/likes/received") return 12_000;
  if (path === "/messages/conversations") return 15_000;
  if (path === "/discover/feed") return 8_000;
  if (path === "/auth/me") return 5_000;
  if (path === "/profiles/me") return 12_000;
  if (path === "/profiles/me/risk") return 15_000;
  if (path === "/subscriptions/me") return 15_000;
  if (path === "/daily/boosts") return 10_000;
  if (path.startsWith("/auth/social/providers")) return 30_000;
  /** Align with CHAT_THREAD_POLL_MS so steady polling is not skipped every other tick. */
  if (/^\/messages\/\d+$/.test(path)) return 16_000;
  if (path.startsWith("/profile/trust")) return 5_000;
  if (path.startsWith("/profiles/")) return Math.max(2_500, GLOBAL_GET_COOLDOWN_MS);
  return GLOBAL_GET_COOLDOWN_MS;
}

function debounceDelayMs(path: string, method: string): number {
  if (method === "GET" && path === "/nav/badges") return 1_500;
  // Collapse bursty profile edits (rapid toggles / double-submit) into fewer round-trips.
  if (method === "PATCH" && path === "/profiles/me") return 400;
  return 0;
}

function cloneForCache<T>(v: T): T {
  if (v === null || typeof v !== "object") return v;
  try {
    return JSON.parse(JSON.stringify(v)) as T;
  } catch {
    return v;
  }
}

function getCachedPayload<T>(cacheKey: string | null, allowExpired: boolean = false): T | undefined {
  if (!cacheKey) return undefined;
  const hit = getResponseCache.get(cacheKey);
  if (!hit) return undefined;
  if (!allowExpired && hit.expiresAt <= Date.now()) return undefined;
  return cloneForCache(hit.payload) as T;
}

function withCallerAbort<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(new ApiRequestAbortedError());
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => {
      signal.removeEventListener("abort", onAbort);
      reject(new ApiRequestAbortedError());
    };
    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(
      (value) => {
        signal.removeEventListener("abort", onAbort);
        resolve(value);
      },
      (error) => {
        signal.removeEventListener("abort", onAbort);
        reject(error);
      },
    );
  });
}

/** True for errors that background `softFail` callers should treat as empty state (no overlay). */
function softFailSilentReturn(e: unknown): boolean {
  if (isRequestAborted(e)) return true;
  if (e instanceof ApiThrottleSkipError) return true;
  if (e instanceof RateLimitError) return true;
  if (e instanceof ApiUnauthorizedError) return true;
  if (e instanceof ApiRequestAbortedError) return true;
  if (e instanceof Error) {
    const m = e.message || "";
    if (m.includes("API unreachable")) return true;
    if (m === "Request aborted") return true;
    if (m === "THROTTLE_SKIP") return true;
  }
  return false;
}

function finalizeSoftFailPromise<T>(p: Promise<T>, signal: AbortSignal | undefined, softFail: boolean | undefined): Promise<T> {
  const chained = withCallerAbort(p, signal);
  if (softFail !== true) return chained;
  return chained.catch((err: unknown) => {
    if (softFailSilentReturn(err)) return undefined as T;
    throw err;
  }) as Promise<T>;
}

/** Drop cached GETs (call on logout, token change, or after mutations). */
export function invalidateApiGetCache(pathPrefix?: string) {
  if (pathPrefix == null || pathPrefix === "") {
    getResponseCache.clear();
    return;
  }
  for (const k of getResponseCache.keys()) {
    if (k.endsWith(pathPrefix) || k.includes(pathPrefix)) getResponseCache.delete(k);
  }
}

/** In-flight + short-window dedupe key: same method + relative path (+ body for mutating requests). */
function dedupeKey(path: string, method: string, body: RequestInit["body"]): string | null {
  const m = method.toUpperCase();
  if (m === "GET" || m === "HEAD") return `${m}:${API_URL}${path}`;
  if ((m === "POST" || m === "PUT" || m === "PATCH") && body != null) {
    const s = typeof body === "string" ? body : "";
    return `${m}:${API_URL}${path}:${s.slice(0, 400)}`;
  }
  return `${m}:${API_URL}${path}`;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- JSON API surface is heterogeneous across the app
export async function apiFetch<T = any>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { skipAuthRedirect, skipThrottle, skipCache, metaReason, softFail, ...fetchOpts } = options;
  const method = ((fetchOpts.method as string) || "GET").toUpperCase();

  if (typeof window !== "undefined") {
    hydrateAuthStateFromStorage();
    if (authState === "unauthorized" && !isPublicApiPath(path, method)) {
      if (softFail === true) return Promise.resolve(undefined as T);
      if (LOG_API) console.debug("[neyra] apiFetch blocked (unauthorized)", path, method, metaReason ?? "");
      throw new ApiUnauthorizedError(path);
    }
  }

  // Caller-controlled throttle bypass: used for explicit manual refresh and post-action reconciliation.
  // Keep defaults conservative; callers should only set skipThrottle when they genuinely need a refresh now.
  const canShareInflight = method === "GET" || method === "HEAD";
  const key = canShareInflight
    ? dedupeKey(path, method, fetchOpts.body)
    : fetchOpts.signal
      ? null
      : dedupeKey(path, method, fetchOpts.body);
  const cacheKey = getCacheKey(path, method);
  const cacheTtl = skipCache ? 0 : getGetCacheTtlMs(path);
  const throttleGap = throttleGapMs(path, method);
  const gap = skipThrottle ? 0 : throttleGap;
  const debounceMs = debounceDelayMs(path, method);
  const tKey = `${method}:${path}`;
  const throttleApplies = method === "GET" && gap > 0;
  const now = Date.now();
  const backoffUntil = rateLimitBackoffUntil.get(tKey) ?? 0;

  if (fetchOpts.signal?.aborted) {
    if (softFail === true) return Promise.resolve(undefined as T);
    throw new ApiRequestAbortedError();
  }
  if (cacheKey && cacheTtl > 0) {
    const cached = getCachedPayload<T>(cacheKey);
    if (cached !== undefined) {
      if (LOG_API) console.log("[neyra] apiFetch cache hit", path, metaReason || "");
      return cached;
    }
  }

  if (key) {
    const existing = inflightDedupe.get(key);
    if (existing) {
      if (LOG_API) console.log("API DEDUPE join:", path, method, metaReason || "");
      return finalizeSoftFailPromise(existing as Promise<T>, fetchOpts.signal, softFail);
    }
  }

  if (backoffUntil > now) {
    const cached = getCachedPayload<T>(cacheKey, true);
    if (cached !== undefined) {
      if (LOG_API) console.log("[neyra] apiFetch rate-limit backoff -> stale cache", path, metaReason || "");
      return cached;
    }
    if (LOG_API) {
      console.warn("[neyra] apiFetch rate-limit backoff", {
        path,
        metaReason,
        retryInMs: backoffUntil - now,
      });
    }
    if (softFail === true) return Promise.resolve(undefined as T);
    throw new RateLimitError(path, 429, "Rate limited");
  }
  if (backoffUntil > 0) rateLimitBackoffUntil.delete(tKey);

  if (throttleApplies && key) {
    const last = throttleLastDoneAt.get(tKey) ?? 0;
    const since = now - last;
    if (since < gap) {
      const cached = getCachedPayload<T>(cacheKey, true);
      if (cached !== undefined) {
        if (LOG_API) console.log("[neyra] apiFetch throttle -> stale cache", path, metaReason || "");
        return cached;
      }
      if (cacheKey && cacheTtl > 0) {
        const stale = getResponseCache.get(cacheKey);
        if (stale?.payload !== undefined) {
          if (LOG_API) console.log("[neyra] apiFetch throttle → stale cache", path, metaReason || "");
          return Promise.resolve(cloneForCache(stale.payload) as T);
        }
      }
      if (LOG_API) {
        console.log("[neyra] apiFetch throttle skip", { path, metaReason, gapMs: gap, sinceLastMs: since });
      }
      if (softFail === true) return Promise.resolve(undefined as T);
      throw new ApiThrottleSkipError(path, metaReason);
    }
  }

  logApiCall(path, method, metaReason);

  const token = getToken();
  logAuthRequestContext("request", path, method, metaReason);
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((fetchOpts.headers as Record<string, string>) || {}),
  };
  // Strict single-language UI: always send UI locale with requests (best-effort, no i18n import to avoid cycles).
  try {
    if (typeof window !== "undefined") {
      const raw = String(localStorage.getItem("neyra:locale") || "").trim();
      if (raw && !headers["X-UI-Locale"]) headers["X-UI-Locale"] = raw;
      if (raw && !headers["X-Locale"]) headers["X-Locale"] = raw;
      if (raw && !headers["X-Neyra-Locale"]) headers["X-Neyra-Locale"] = raw;
    }
  } catch {
    /* ignore */
  }
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const run = async (): Promise<T> => {
    if (typeof window !== "undefined" && authState === "unauthorized" && !isPublicApiPath(path, method)) {
      if (softFail === true) return undefined as T;
      throw new ApiUnauthorizedError(path);
    }
    const url = `${API_URL}${path}`;
    const requestInit =
      canShareInflight && fetchOpts.signal
        ? { ...fetchOpts, signal: undefined }
        : fetchOpts;
    if (debounceMs > 0) {
      if (LOG_API) {
        console.log("[neyra] apiFetch debounce", {
          path,
          method,
          delayMs: debounceMs,
          metaReason,
        });
      }
      await sleepMs(debounceMs);
    }

    for (let attempt = 0; attempt <= TRANSIENT_NETWORK_RETRIES; attempt += 1) {
      let res: Response;
      try {
        // Always include cookies for same-site and cross-site dev auth flows.
        // Many endpoints still use Bearer tokens, but cookie-based sessions require this.
        const credentials = (requestInit as RequestInit).credentials ?? "include";
        res = await fetch(url, { ...requestInit, headers, cache: "no-store", credentials });
      } catch (e) {
        if (isAbortError(e)) {
          throw new ApiRequestAbortedError(e);
        }
        // Avoid noisy logs for abort-shaped failures some runtimes surface differently.
        if (requestInit.signal?.aborted || fetchOpts.signal?.aborted) {
          throw new ApiRequestAbortedError(e);
        }
        if (attempt < TRANSIENT_NETWORK_RETRIES) {
          const delayMs = 250 * Math.pow(2, attempt);
          if (LOG_API) console.warn("[neyra] API transient network failure; retrying", { url, path, attempt, delayMs, error: e });
          await sleepMs(delayMs);
          continue;
        }
        logUnreachableThrottled(normalizeApiPath(path), {
          phase: "fetch",
          metaReason,
          error: e instanceof Error ? e.message : String(e),
        });
        if (softFail === true) {
          return undefined as T;
        }
        throw new Error(formatUnreachableError(API_URL));
      }

      let text: string;
      try {
        text = await res.text();
      } catch (e) {
        if (isAbortError(e)) {
          throw new ApiRequestAbortedError(e);
        }
        if (res.status === 429) {
          if (LOG_API) console.warn("[neyra] API rate limited", { path, status: res.status, metaReason, phase: "read-body" });
          if (method === "GET" || method === "HEAD") {
            const retryAfterMs = parseRetryAfterMs(res.headers.get("Retry-After"));
            rateLimitBackoffUntil.set(tKey, Date.now() + (retryAfterMs ?? RATE_LIMIT_BACKOFF_MS));
          }
          if (softFail === true) return undefined as T;
          throw new RateLimitError(path, res.status, "Rate limited");
        }
        if (LOG_API) {
          console.warn("[neyra] API response body read failed", { url, path, error: e, phase: "read-body", status: res.status });
        }
        if (softFail === true) return undefined as T;
        throw new Error(`Request failed (${res.status})`);
      }

      if (res.status === 401) {
        if (softFail === true) return undefined as T;
        logAuthUnauthorizedResponse(path, method, metaReason);
        if (typeof window !== "undefined" && !skipAuthRedirect) {
          authHydrated = true;
          authState = "unauthorized";
          const onPath = typeof window !== "undefined" ? window.location.pathname || "" : "";
          const authSurface =
            onPath.startsWith("/login") ||
            onPath.startsWith("/signup") ||
            onPath.startsWith("/intro") ||
            onPath.startsWith("/auth/social/callback") ||
            onPath.startsWith("/account/restore") ||
            onPath.startsWith("/verify-email");
          if (!authRedirectIssued) {
            authRedirectIssued = true;
            clearAuth();
            if (!authSurface) {
              dispatchAuthExpired();
            }
          } else {
            clearAuth();
          }
        }
        throw new ApiUnauthorizedError(path);
      }

      if (res.status === 429) {
        const detail = formatApiError(text, res.status).trim();
        const msg =
          detail && !/^rate\s*limited\b/i.test(detail) ? `Rate limited: ${detail}` : "Rate limited";
        if (LOG_API) console.warn("[neyra] API rate limited", { path, status: res.status, metaReason });
        if (method === "GET" || method === "HEAD") {
          const retryAfterMs = parseRetryAfterMs(res.headers.get("Retry-After"));
          const delayMs = retryAfterMs ?? RATE_LIMIT_BACKOFF_MS;
          rateLimitBackoffUntil.set(tKey, Date.now() + delayMs);
        }
        if (softFail === true) return undefined as T;
        throw new RateLimitError(path, res.status, msg);
      }

      if (!res.ok) {
        if (softFail === true) return undefined as T;
        if (res.status === 402) {
          throw new ApiPaywallError(path, res.status, formatApiError(text, res.status));
        }
        throw new Error(formatApiError(text, res.status));
      }
      try {
        return (text ? JSON.parse(text) : null) as T;
      } catch {
        return text as T;
      }
    }
    if (softFail === true) return undefined as T;
    throw new Error(formatUnreachableError(API_URL));
  };

  const promise = run()
    .then((parsed) => {
      if (parsed === undefined && softFail === true) {
        rateLimitBackoffUntil.delete(tKey);
        return undefined as T;
      }
      if (typeof window !== "undefined" && authState === "unknown" && getToken() && !isPublicApiPath(path, method)) {
        authState = "authorized";
      }
      if (cacheKey && cacheTtl > 0 && method === "GET" && parsed !== undefined) {
        getResponseCache.set(cacheKey, { expiresAt: Date.now() + cacheTtl, payload: cloneForCache(parsed) });
      }
      rateLimitBackoffUntil.delete(tKey);
      return parsed;
    })
    .finally(() => {
      if (key) inflightDedupe.delete(key);
      if (throttleApplies) throttleLastDoneAt.set(tKey, Date.now());
    });

  if (key) inflightDedupe.set(key, promise);

  return finalizeSoftFailPromise(promise as Promise<T>, fetchOpts.signal, softFail);
}

/** Central entry: all JSON API traffic should use `apiFetch` (this object is for clarity / future hooks). */
export const apiClient = {
  request: apiFetch,
  invalidateGetCache: invalidateApiGetCache,
};

/** Multipart upload (does not set Content-Type — browser sets boundary). */
export async function apiUpload(
  path: string,
  formData: FormData,
  options: Pick<ApiFetchOptions, "skipAuthRedirect" | "metaReason" | "signal"> = {},
) {
  const { skipAuthRedirect, metaReason, signal } = options;
  if (typeof window !== "undefined") {
    hydrateAuthStateFromStorage();
    if (authState === "unauthorized" && !isPublicApiPath(path, "POST")) {
      throw new ApiUnauthorizedError(path);
    }
  }
  logApiCall(path, "POST", metaReason);
  const token = getToken();
  logAuthRequestContext("upload", path, "POST", metaReason);
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const url = `${API_URL}${path}`;
  const runOnce = async (): Promise<{ res: Response; text: string }> => {
    let res: Response;
    try {
      res = await fetch(url, {
        method: "POST",
        headers,
        body: formData,
        cache: "no-store",
        credentials: "include",
        signal,
      });
    } catch (e) {
      if (isAbortError(e)) {
        throw new ApiRequestAbortedError(e);
      }
      console.error("[neyra] API unreachable", { url, path, error: e, phase: "upload-fetch" });
      throw new Error(formatUnreachableError(API_URL));
    }

    let text: string;
    try {
      text = await res.text();
    } catch (e) {
      if (isAbortError(e)) {
        throw new ApiRequestAbortedError(e);
      }
      if (res.status === 429) {
        if (LOG_API) console.warn("[neyra] API rate limited (upload)", { path, status: res.status, metaReason, phase: "read-body" });
        throw new RateLimitError(path, res.status, "Rate limited");
      }
      if (LOG_API) {
        console.warn("[neyra] API response body read failed", { url, path, error: e, phase: "upload-read-body", status: res.status });
      }
      throw new Error(`Request failed (${res.status})`);
    }
    return { res, text };
  };

  // Upload-specific hardening: a 401 can happen due to transient cookie/token race.
  // Refresh auth ONCE and retry before showing "session expired".
  let attempt = 0;
  for (;;) {
    const { res, text } = await runOnce();
    if (res.status !== 401) {
      if (res.status === 429) {
        const detail = formatApiError(text, res.status).trim();
        const msg =
          detail && !/^rate\s*limited\b/i.test(detail) ? `Rate limited: ${detail}` : "Rate limited";
        if (LOG_API) console.warn("[neyra] API rate limited (upload)", { path, status: res.status, metaReason });
        throw new RateLimitError(path, res.status, msg);
      }
      if (!res.ok) {
        if (res.status === 402) {
          throw new ApiPaywallError(path, res.status, formatApiError(text, res.status));
        }
        throw new Error(formatApiError(text, res.status));
      }
      if (typeof window !== "undefined" && authState === "unknown" && getToken() && !isPublicApiPath(path, "POST")) {
        authState = "authorized";
      }
      try {
        return text ? JSON.parse(text) : null;
      } catch {
        return text;
      }
    }

    // 401
    logAuthUnauthorizedResponse(path, "POST", metaReason);
    if (attempt >= 1 || typeof window === "undefined") break;
    attempt += 1;
    try {
      // Force refresh auth snapshot (single-flight) and promote api auth state if ok.
      const r = await getAuthBootstrapResult({ force: true });
      applyAuthBootstrapResult(r);
      // Retry the upload once after refresh.
      continue;
    } catch {
      break;
    }
  }

  // Definitive 401 after retry → proceed with existing auth-expired behavior.
  if (typeof window !== "undefined" && !skipAuthRedirect) {
    authHydrated = true;
    authState = "unauthorized";
    const onPath = typeof window !== "undefined" ? window.location.pathname || "" : "";
    const authSurface =
      onPath.startsWith("/login") ||
      onPath.startsWith("/signup") ||
      onPath.startsWith("/intro") ||
      onPath.startsWith("/auth/social/callback") ||
      onPath.startsWith("/account/restore") ||
      onPath.startsWith("/verify-email");
    if (!authRedirectIssued) {
      authRedirectIssued = true;
      clearAuth();
      if (!authSurface) {
        dispatchAuthExpired();
      }
    } else {
      clearAuth();
    }
  }
  throw new ApiUnauthorizedError(path);
}
