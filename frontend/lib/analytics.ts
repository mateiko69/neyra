import { apiFetch, getAuthState, getToken, hydrateAuthStateFromStorage } from "./api";
import { appendGrowthMetadata } from "./analytics/growthContext";
import { recordLocalAnalyticsEvent } from "./analyticsLocalStore";

const DEBUG_HOT =
  typeof process !== "undefined" && process.env.NEXT_PUBLIC_DEBUG_API === "1";

const FLUSH_MS = 2_000;
const MIN_BATCH_INTERVAL_MS = 3_000;
const MAX_BATCH = 40;

type Queued = { name: string; payload: Record<string, unknown> };

let queue: Queued[] = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;
let flushInFlight: Promise<void> | null = null;
let lastBatchSentAt = 0;

function signature(item: Queued): string {
  return `${item.name}:${JSON.stringify(item.payload)}`;
}

function enqueue(item: Queued) {
  const sig = signature(item);
  queue = queue.filter((q) => signature(q) !== sig);
  queue.push(item);
}

function scheduleFlush() {
  if (flushTimer != null) return;
  flushTimer = setTimeout(() => {
    flushTimer = null;
    void flushQueue();
  }, FLUSH_MS);
}

async function flushQueue(): Promise<void> {
  if (queue.length === 0) return;
  if (flushInFlight) return flushInFlight;
  flushInFlight = (async () => {
    try {
      // Max 1 analytics batch per 3 seconds per page to prevent API spam loops.
      const now = Date.now();
      const waitMs = MIN_BATCH_INTERVAL_MS - (now - lastBatchSentAt);
      if (waitMs > 0) {
        // Keep queue intact; try again later.
        setTimeout(() => scheduleFlush(), Math.min(waitMs + 25, MIN_BATCH_INTERVAL_MS));
        return;
      }

      const batch = queue.splice(0, MAX_BATCH);
      if (!batch.length) return;
      hydrateAuthStateFromStorage();
      if (!getToken() || getAuthState() === "unauthorized") {
        queue = [];
        return;
      }
      try {
        await apiFetch("/analytics/track/batch", {
          method: "POST",
          body: JSON.stringify({ events: batch }),
          metaReason: "analytics:batch",
          skipThrottle: true,
        });
        lastBatchSentAt = Date.now();
        if (DEBUG_HOT) console.debug("[neyra][analytics]", "batch ok", batch.length);
      } catch {
        // Fail-open: keep events for later instead of spamming /track per-event.
        queue = [...batch, ...queue];
        setTimeout(() => scheduleFlush(), MIN_BATCH_INTERVAL_MS);
      }
    } finally {
      flushInFlight = null;
      if (queue.length > 0) scheduleFlush();
    }
  })();
  return flushInFlight;
}

export async function trackAnalyticsEvent(name: string, payload: Record<string, unknown> = {}): Promise<void> {
  const eventName = String(name || "").trim();
  if (!eventName) return;
  const enriched = appendGrowthMetadata(payload);
  recordLocalAnalyticsEvent(eventName, enriched);
  enqueue({ name: eventName, payload: enriched });
  scheduleFlush();
}

// Test hook: allows Playwright to generate events without dynamic imports.
try {
  if (typeof window !== "undefined") (window as any).__neyra_trackAnalyticsEvent = trackAnalyticsEvent;
} catch {
  // ignore
}
