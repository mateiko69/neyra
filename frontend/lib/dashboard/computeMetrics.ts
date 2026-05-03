import type { LocalAnalyticsEvent } from "../analyticsLocalStore";

export type WindowKey = "today" | "7d" | "30d" | "session";

export type MetricsResult = {
  window: WindowKey;
  fromTs: number;
  toTs: number;
  counts: Record<string, number>;
  rates: Record<string, number | null>;
  topContexts: { key: string; count: number }[];
  topVariants: { key: string; count: number }[];
};

function startOfTodayMs(nowMs: number): number {
  const d = new Date(nowMs);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

function clampRate(num: number, den: number): number | null {
  if (!Number.isFinite(num) || !Number.isFinite(den) || den <= 0) return null;
  return Math.max(0, Math.min(1, num / den));
}

function getSessionId(events: LocalAnalyticsEvent[]): string | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.name === "local_session_started") return String((e.payload as any)?.session_id || "") || null;
  }
  const last = events[events.length - 1];
  return last ? String((last.payload as any)?._local_session_id || "") || null : null;
}

export function computeDashboardMetrics(events: LocalAnalyticsEvent[], window: WindowKey): MetricsResult {
  const now = Date.now();
  const toTs = now;
  const fromTs =
    window === "today"
      ? startOfTodayMs(now)
      : window === "7d"
        ? now - 7 * 24 * 60 * 60 * 1000
        : window === "30d"
          ? now - 30 * 24 * 60 * 60 * 1000
          : 0;

  const sid = window === "session" ? getSessionId(events) : null;

  const filtered = events.filter((e) => {
    if (!e || typeof e.ts !== "number") return false;
    if (window !== "session") return e.ts >= fromTs && e.ts <= toTs;
    return sid ? String((e.payload as any)?._local_session_id || "") === sid : false;
  });

  const counts: Record<string, number> = {};
  for (const e of filtered) counts[e.name] = (counts[e.name] || 0) + 1;

  const rates: Record<string, number | null> = {};

  // AI effectiveness
  const aiSends = counts["ai_assist_sent_after_use"] || 0;
  rates["ai_assist_usage_rate"] = clampRate(aiSends, counts["local_session_started"] || 1);
  rates["ai_assist_success_reply_received_rate"] = clampRate(counts["ai_assist_success_reply_received"] || 0, aiSends);
  rates["ai_assist_success_readiness_improved_rate"] = clampRate(
    counts["ai_assist_success_readiness_improved"] || 0,
    counts["ai_readiness_viewed"] || 0,
  );
  rates["ai_assist_success_recovery_worked_rate"] = clampRate(
    counts["ai_assist_success_recovery_worked"] || 0,
    counts["ai_recovery_suggestion_clicked"] || 0,
  );
  rates["ai_assist_success_escalation_progressed_rate"] = clampRate(
    counts["ai_assist_success_escalation_progressed"] || 0,
    counts["ai_escalation_action_clicked"] || 0,
  );

  // Monetization (Plus hooks)
  const hookSeen = counts["premium_plus_hook_seen"] || 0;
  const hookClicked = counts["premium_plus_hook_clicked"] || 0;
  rates["premium_plus_hook_ctr"] = clampRate(hookClicked, hookSeen);

  const hookConverted = counts["premium_plus_hook_converted"] || 0;
  rates["premium_plus_hook_conversion_rate"] = clampRate(hookConverted, hookSeen);

  // Top contexts / variants
  const ctxCounts = new Map<string, number>();
  const varCounts = new Map<string, number>();
  for (const e of filtered) {
    if (e.name.startsWith("premium_plus_hook_")) {
      const ctx = String((e.payload as any)?.context || "");
      const variant = String((e.payload as any)?.variant_id || "");
      if (ctx) ctxCounts.set(ctx, (ctxCounts.get(ctx) || 0) + 1);
      if (ctx && variant) varCounts.set(`${ctx}:${variant}`, (varCounts.get(`${ctx}:${variant}`) || 0) + 1);
    }
  }

  const topContexts = Array.from(ctxCounts.entries())
    .map(([key, count]) => ({ key, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 6);

  const topVariants = Array.from(varCounts.entries())
    .map(([key, count]) => ({ key, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 8);

  return { window, fromTs, toTs, counts, rates, topContexts, topVariants };
}

