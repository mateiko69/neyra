/**
 * Single source of truth for persisted auth session (browser).
 */

export const TOKEN_STORAGE_KEY = "neyra:token" as const;
const TOKEN_LEGACY_KEYS = ["access_token", "token"] as const;

/** Optional client caches — clear on session invalidation. */
export const USER_CACHE_KEY = "neyra:user" as const;
export const PROFILE_CACHE_KEY = "neyra:profile" as const;
export const ONBOARDING_CACHE_KEY = "neyra:onboarding" as const;

const EXPLICIT_CLEAR_KEYS = [
  TOKEN_STORAGE_KEY,
  USER_CACHE_KEY,
  PROFILE_CACHE_KEY,
  ONBOARDING_CACHE_KEY,
  ...TOKEN_LEGACY_KEYS,
] as const;

/** Reject obviously broken / empty bearer values before hitting the API. */
export function hasValidTokenShape(token: string | null | undefined): boolean {
  const t = String(token ?? "").trim();
  if (t.length < 12) return false;
  const parts = t.split(".");
  if (parts.length === 3 && parts.every((p) => p.length > 0)) return true;
  return t.length >= 16;
}

export function getStoredToken(): string {
  if (typeof window === "undefined") return "";
  const primary = localStorage.getItem(TOKEN_STORAGE_KEY);
  if (primary) return primary;
  for (const key of TOKEN_LEGACY_KEYS) {
    const v = localStorage.getItem(key);
    if (v) {
      try {
        localStorage.setItem(TOKEN_STORAGE_KEY, v);
      } catch {
        /* ignore */
      }
      return v;
    }
  }
  return "";
}

export function setStoredToken(token: string): void {
  if (typeof window === "undefined") return;
  const t = String(token || "").trim();
  if (!t) return;
  try {
    localStorage.setItem(TOKEN_STORAGE_KEY, t);
    for (const key of TOKEN_LEGACY_KEYS) {
      localStorage.setItem(key, t);
    }
  } catch {
    /* quota / private mode */
  }
}

/** Full logout: tokens, profile caches, sessionStorage (tab / AI caches). Keeps locale, intro_seen, auth version. */
export function clearStoredSession(): void {
  if (typeof window === "undefined") return;
  for (const key of EXPLICIT_CLEAR_KEYS) {
    try {
      localStorage.removeItem(key);
    } catch {
      /* ignore */
    }
  }
  try {
    sessionStorage.clear();
  } catch {
    /* ignore */
  }
}
