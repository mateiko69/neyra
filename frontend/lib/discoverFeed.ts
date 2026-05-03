import { ApiPaywallError, ApiThrottleSkipError, apiFetch } from "./api";
import { logAiData, logAiGate } from "./aiDebug";

let inflight: Promise<unknown> | null = null;
let lastOk: unknown = null;

/**
 * Single-flight GET /discover/feed: concurrent callers share one HTTP request (Strict Mode, double refresh, etc.).
 * `skipCache` forces a network round-trip (explicit refresh / refill after swipe).
 */
export function fetchDiscoverFeed(
  reason: string,
  opts?: { skipCache?: boolean; skipThrottle?: boolean },
): { promise: Promise<unknown>; isPrimary: boolean } {
  if (typeof process !== "undefined" && process.env.NODE_ENV === "development") {
    console.log(
      "[neyra] discover/feed",
      inflight ? `join in-flight (${reason})` : `start (${reason})`,
      opts?.skipCache ? "skipCache" : "",
    );
  }
  if (inflight) {
    return { promise: inflight, isPrimary: false };
  }
  inflight = apiFetch("/discover/feed?limit=12", {
    metaReason: reason,
    skipCache: opts?.skipCache === true,
    skipThrottle: opts?.skipThrottle === true,
    softFail: true,
  })
    .then((response) => {
      if (response === undefined) return lastOk ?? [];
      logAiData("discover/feed", response);
      lastOk = response;
      return response;
    })
    .catch((error) => {
      if (error instanceof ApiThrottleSkipError) {
        return lastOk ?? [];
      }
      if (error instanceof ApiPaywallError) {
        logAiGate("discover/feed", {
          reason,
          skipCache: opts?.skipCache === true,
          error: error instanceof Error ? error.message : String(error),
        });
        throw error;
      }
      logAiGate("discover/feed", {
        reason,
        skipCache: opts?.skipCache === true,
        error: error instanceof Error ? error.message : String(error),
      });
      return lastOk ?? [];
    })
    .finally(() => {
      inflight = null;
    });
  return { promise: inflight, isPrimary: true };
}
