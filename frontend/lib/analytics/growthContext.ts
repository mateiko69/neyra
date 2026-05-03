import { getToken } from "../api";
import { getCurrentUiLocale } from "../i18n";

const TIER_KEY = "neyra:growth_user_tier_v1";

/**
 * Best-effort plan tier for analytics (sync). Primed from AppNavigation when /subscriptions/me resolves.
 */
export function primeGrowthUserTier(tier: string): void {
  if (typeof window === "undefined") return;
  try {
    const t = String(tier || "free").trim() || "free";
    sessionStorage.setItem(TIER_KEY, t);
  } catch {
    /* ignore */
  }
}

export function getGrowthUserTier(): string {
  if (typeof window === "undefined") return "unknown";
  if (!getToken()) return "anonymous";
  try {
    return sessionStorage.getItem(TIER_KEY) || "unknown";
  } catch {
    return "unknown";
  }
}

export function getGrowthLocale(): string {
  try {
    return getCurrentUiLocale() || "en";
  } catch {
    return "en";
  }
}

/** Attach defaults for funnel dashboards (callers may override). */
export function appendGrowthMetadata(payload: Record<string, unknown>): Record<string, unknown> {
  const locale = typeof payload.locale === "string" && payload.locale.trim() ? payload.locale : getGrowthLocale();
  const user_tier =
    typeof payload.user_tier === "string" && payload.user_tier.trim() ? payload.user_tier : getGrowthUserTier();
  return { ...payload, locale, user_tier };
}
