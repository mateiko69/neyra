export type AiTier = "free" | "premium" | "premium_plus";

export function normalizePlanCode(raw: unknown): AiTier {
  const v = String(raw ?? "").trim().toLowerCase();
  if (v === "premium_plus" || v === "premiumplus" || v === "plus") return "premium_plus";
  if (v === "premium") return "premium";
  return "free";
}

export function resolveAiTier(input: { isPremium: boolean; planCode?: unknown }): AiTier {
  if (!input.isPremium) return "free";
  const plan = normalizePlanCode(input.planCode);
  // If backend says premium but planCode is missing, treat as premium (not free).
  return plan === "free" ? "premium" : plan;
}

/** Recent messages sent as AI conversation context (chat brain / rewrite). */
export function aiChatContextMessageLimit(tier: AiTier): number {
  return tier === "free" ? 5 : 50;
}

