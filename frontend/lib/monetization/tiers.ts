import { normalizePlanCode, type AiTier } from "../chat/aiTier";

export type PlanTier = AiTier;

export type SubscriptionSnapshot = {
  status?: string | null;
  plan_code?: string | null;
  planCode?: string | null;
};

export function resolvePlanTier(snapshot: SubscriptionSnapshot | null | undefined): PlanTier {
  const code = snapshot ? (snapshot.plan_code ?? snapshot.planCode ?? "free") : "free";
  return normalizePlanCode(code);
}

export function isTierAtLeast(tier: PlanTier, required: PlanTier): boolean {
  const order: Record<PlanTier, number> = { free: 0, premium: 1, premium_plus: 2 };
  return order[tier] >= order[required];
}

