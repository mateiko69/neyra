import { readLocalAnalyticsEvents } from "../analyticsLocalStore";

/** Canonical funnel names for client-side aggregation (mirrors growth instrumentation). */
export const GROWTH_FUNNEL_EVENTS = [
  "landing_view",
  "signup_started",
  "signup_completed",
  "onboarding_completed",
  "discover_viewed",
  "like_sent",
  "match_created",
  "chat_opened",
  "ai_used",
  "ai_limit_hit",
  "paywall_shown",
  "paywall_opened",
  "paywall_cta_clicked",
  "trial_started",
  "premium_purchased",
] as const;

export type GrowthFunnelSummary = {
  counts: Record<string, number>;
  paywallBySurface: Record<string, number>;
  /** `premium_purchased` counts by payload `channel` (best-effort). */
  premiumPurchasedByChannel: Record<string, number>;
  dropOffApprox: Array<{ from: string; to: string; fromCount: number; toCount: number; rate: number | null }>;
};

/**
 * Frontend-only rollup from persisted local analytics (see `recordLocalAnalyticsEvent`).
 * For product dashboards / DevTools; server truth remains `/analytics/track/batch`.
 */
const EXTRA_FUNNEL_COUNT_EVENTS = ["paywall_clicked", "conversion_after_reply", "conversion_after_match"] as const;

const FUNNEL_SET = new Set<string>([...GROWTH_FUNNEL_EVENTS, ...EXTRA_FUNNEL_COUNT_EVENTS]);

export function summarizeGrowthFunnelLocal(): GrowthFunnelSummary {
  const events = readLocalAnalyticsEvents();
  const counts: Record<string, number> = {};
  const paywallBySurface: Record<string, number> = {};
  const premiumPurchasedByChannel: Record<string, number> = {};

  for (const e of events) {
    const n = String(e.name || "").trim();
    if (!n) continue;
    if (FUNNEL_SET.has(n)) {
      counts[n] = (counts[n] ?? 0) + 1;
    }
    if (n === "paywall_shown" || n === "paywall_opened" || n === "paywall_cta_clicked" || n === "paywall_clicked") {
      const surface = String((e.payload && typeof e.payload === "object" ? (e.payload as Record<string, unknown>).surface : "") ?? "unknown");
      const key = surface.trim() || "unknown";
      paywallBySurface[key] = (paywallBySurface[key] ?? 0) + 1;
    }
    if (n === "premium_purchased") {
      const pl = e.payload && typeof e.payload === "object" ? (e.payload as Record<string, unknown>) : null;
      const ch = String(pl?.channel ?? pl?.surface ?? "unknown").trim() || "unknown";
      premiumPurchasedByChannel[ch] = (premiumPurchasedByChannel[ch] ?? 0) + 1;
    }
  }

  const ordered = [...GROWTH_FUNNEL_EVENTS];
  const dropOffApprox: GrowthFunnelSummary["dropOffApprox"] = [];
  for (let i = 0; i < ordered.length - 1; i++) {
    const from = ordered[i];
    const to = ordered[i + 1];
    const fromCount = counts[from] ?? 0;
    const toCount = counts[to] ?? 0;
    const rate = fromCount > 0 ? toCount / fromCount : null;
    dropOffApprox.push({ from, to, fromCount, toCount, rate });
  }

  return { counts, paywallBySurface, premiumPurchasedByChannel, dropOffApprox };
}
