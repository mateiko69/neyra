import { trackAnalyticsEvent } from "./analytics";

export type PremiumPlusHookContext = "ai_styles" | "compatibility" | "recovery" | "coach" | "escalation" | "trust";

export type PremiumPlusHookPayload = {
  context: PremiumPlusHookContext;
  plan_tier: "free" | "premium" | "premium_plus";
  thread_state?: "empty" | "active";
  surface?: string;
  variant_id?: string;
  copy_id?: string;
};

export async function trackPremiumPlusHookContext(payload: PremiumPlusHookPayload): Promise<void> {
  await trackAnalyticsEvent("premium_plus_hook_context", payload);
}

export async function trackPremiumPlusHookSeen(payload: PremiumPlusHookPayload): Promise<void> {
  await trackPremiumPlusHookContext(payload);
  await trackAnalyticsEvent("premium_plus_hook_seen", payload);
}

export async function trackPremiumPlusHookClicked(payload: PremiumPlusHookPayload): Promise<void> {
  await trackPremiumPlusHookContext(payload);
  await trackAnalyticsEvent("premium_plus_hook_clicked", payload);
}

