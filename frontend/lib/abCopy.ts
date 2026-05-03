import { apiFetch } from "./api";

export const AB_EXPERIMENT_KEYS = [
  "chat.opener.nudge",
  "paywall.message",
  "onboarding.cta",
  "paywall.modal.copy",
  "growth.trial.duration",
  "ai.limit.copy",
  "subscription.pricing.copy",
] as const;

/** Experiments to attribute on checkout / premium_purchased (conversion per variant). */
export const AB_PREMIUM_ATTRIBUTION_KEYS: readonly string[] = [
  "paywall.message",
  "paywall.modal.copy",
  "growth.trial.duration",
  "ai.limit.copy",
  "subscription.pricing.copy",
];

export type AbExperimentKey = (typeof AB_EXPERIMENT_KEYS)[number];

export type AbCopyMap = Partial<Record<AbExperimentKey, { variant_id: string; text: string; variant_index?: number }>>;

export async function fetchAbCopy(keys: readonly string[] = AB_EXPERIMENT_KEYS): Promise<AbCopyMap> {
  try {
    const raw = await apiFetch("/growth/ab/resolve", {
      method: "POST",
      metaReason: "ab-resolve",
      skipThrottle: true,
      body: JSON.stringify({ keys: [...keys], record_exposure: true }),
    });
    const copy = raw && typeof raw === "object" ? (raw as Record<string, unknown>).copy : null;
    if (!copy || typeof copy !== "object") return {};
    const out: AbCopyMap = {};
    for (const k of keys) {
      const row = (copy as Record<string, unknown>)[k];
      if (!row || typeof row !== "object") continue;
      const r = row as Record<string, unknown>;
      const text = typeof r.text === "string" ? r.text : "";
      if (!text.trim()) continue;
      out[k as AbExperimentKey] = {
        variant_id: String(r.variant_id ?? ""),
        text,
        variant_index: typeof r.variant_index === "number" ? r.variant_index : undefined,
      };
    }
    return out;
  } catch {
    return {};
  }
}

export function trackAbMetric(metric: "click" | "message_sent" | "reply" | "premium", experimentKey: string, variantId: string): void {
  const vid = String(variantId || "").trim();
  if (!vid) return;
  void apiFetch("/growth/ab/event", {
    method: "POST",
    metaReason: `ab-${metric}`,
    skipThrottle: true,
    body: JSON.stringify({ experiment_key: experimentKey, variant_id: vid, metric }),
  }).catch(() => {});
}

/** Emit `ab_premium` for each resolved variant so conversion rates can be sliced per experiment. */
export function trackAbPremiumConversions(assignments: AbCopyMap | null | undefined): void {
  if (!assignments || typeof assignments !== "object") return;
  for (const key of AB_PREMIUM_ATTRIBUTION_KEYS) {
    const row = assignments[key as keyof AbCopyMap];
    const vid = row && typeof row === "object" ? String((row as { variant_id?: string }).variant_id ?? "").trim() : "";
    if (!vid) continue;
    trackAbMetric("premium", key, vid);
  }
}
