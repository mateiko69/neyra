import { apiFetch } from "./api";

const STORAGE_KEY = "neyra:matches_mark_seen_at";
/** Suppress duplicate POST when Strict Mode remounts or effects overlap (ms). */
const SUPPRESS_MS = 400;

let inflight: Promise<unknown> | null = null;

/**
 * POST /matches/mark-seen at most once per burst: in-flight dedupe + short client throttle.
 */
export function postMatchesMarkSeen(): Promise<unknown> {
  if (typeof window !== "undefined") {
    const last = Number(sessionStorage.getItem(STORAGE_KEY) || 0);
    const now = Date.now();
    if (last > 0 && now - last < SUPPRESS_MS) {
      return Promise.resolve({ ok: true, skipped: true });
    }
  }
  if (inflight) return inflight;

  inflight = apiFetch("/matches/mark-seen", { method: "POST" })
    .then((r) => {
      if (typeof window !== "undefined") {
        sessionStorage.setItem(STORAGE_KEY, String(Date.now()));
      }
      return r;
    })
    .finally(() => {
      inflight = null;
    });

  return inflight;
}
