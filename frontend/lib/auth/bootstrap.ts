import { API_URL } from "../apiBase";
import { getStoredToken } from "./session";

export type AuthBootstrapResult =
  | { status: "ok"; me: unknown }
  | { status: "unauthorized" }
  | { status: "network"; error: unknown }
  | { status: "skipped" };

export type AuthMeSnapshot = {
  user_id: unknown;
  onboarding_required: boolean;
  onboarding_completed: boolean;
  email_verified?: boolean;
};

let cachedSnapshot: AuthMeSnapshot | null = null;
let lastResult: AuthBootstrapResult | null = null;
let inflight: Promise<AuthBootstrapResult> | null = null;

export function parseAuthMeSnapshot(me: unknown): AuthMeSnapshot | null {
  if (!me || typeof me !== "object") return null;
  const o = me as Record<string, unknown>;
  const onboarding_completed = Boolean(o.onboarding_completed);
  const onboarding_required = onboarding_completed ? false : Boolean(o.onboarding_required);
  return {
    user_id: o.user_id ?? null,
    onboarding_required,
    onboarding_completed,
    email_verified: Boolean(o.email_verified),
  };
}

async function fetchAuthMeOnce(): Promise<AuthBootstrapResult> {
  const token = getStoredToken();
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  try {
    const res = await fetch(`${API_URL}/auth/me`, {
      method: "GET",
      credentials: "include",
      headers,
      cache: "no-store",
    });
    if (res.status === 401) {
      cachedSnapshot = null;
      return { status: "unauthorized" };
    }
    const text = await res.text();
    let me: unknown = null;
    if (text) {
      try {
        me = JSON.parse(text);
      } catch {
        me = null;
      }
    }
    if (!res.ok) {
      cachedSnapshot = null;
      return { status: "network", error: new Error(`HTTP ${res.status}`) };
    }
    cachedSnapshot = parseAuthMeSnapshot(me);
    return { status: "ok", me };
  } catch (e) {
    cachedSnapshot = null;
    return { status: "network", error: e };
  }
}

export function invalidateAuthBootstrapCache(): void {
  lastResult = null;
  inflight = null;
  cachedSnapshot = null;
}

/**
 * Apply a fresh GET /auth/me JSON body to the bootstrap cache so AuthRouteGuard and
 * parseAuthMeSnapshot consumers see up-to-date onboarding flags (e.g. after profile save).
 */
export function primeAuthBootstrapFromMe(me: unknown): void {
  cachedSnapshot = parseAuthMeSnapshot(me);
  lastResult = { status: "ok", me };
}

/**
 * Single-flight GET /auth/me for boot and post-login refresh.
 * Does not use apiFetch (avoids 401 redirect / dependency cycles).
 */
export async function getAuthBootstrapResult(opts?: { force?: boolean }): Promise<AuthBootstrapResult> {
  if (typeof window === "undefined") return { status: "skipped" };
  if (opts?.force) invalidateAuthBootstrapCache();
  if (lastResult) return lastResult;
  if (inflight) return inflight;
  inflight = fetchAuthMeOnce()
    .then((r) => {
      lastResult = r;
      return r;
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

export function getAuthMeSnapshot(): AuthMeSnapshot | null {
  return cachedSnapshot;
}
