import { normalizeAppPath } from "./routes";

type NextLikeRouter = { replace: (href: string) => void };

/** Emitted after apiFetch/apiUpload clears session on 401; UI should router.replace /login once. */
export const AUTH_EXPIRED_EVENT = "auth:expired";

export function dispatchAuthExpired(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
}

let lastReplaceKey: string | null = null;

export function resetAuthRedirectLock(): void {
  lastReplaceKey = null;
}

/**
 * Client navigation without replace storms: skip if already on target; at most one replace per (from→to) until lock reset.
 */
export function authSafeReplace(router: NextLikeRouter, pathname: string, target: string): void {
  const cur = normalizeAppPath(pathname);
  const dest = normalizeAppPath(target);
  if (cur === dest) return;
  const key = `${cur}→${dest}`;
  if (lastReplaceKey === key) return;
  lastReplaceKey = key;
  router.replace(target);
}
