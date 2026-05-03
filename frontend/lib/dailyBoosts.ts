import { apiFetch } from "./api";

export type DailyBoosts = {
  day: string;
  opener_remaining: number;
  reply_remaining: number;
  reveal_remaining: number;
  revive_remaining: number;
  streak_days: number;
  /** Extra free-tier chat-brain fetches per day from login streak. */
  streak_bonus_ai_chat: number;
  show_banner: boolean;
  curiosity_like: boolean;
};

export async function fetchDailyBoosts(): Promise<DailyBoosts | null> {
  try {
    const r = await apiFetch("/daily/boosts", { method: "GET", metaReason: "daily-boosts", skipThrottle: true, softFail: true });
    if (r === undefined || !r || typeof r !== "object") return null;
    return r as DailyBoosts;
  } catch {
    return null;
  }
}

export async function consumeDailyBoost(boostType: "opener" | "reply" | "reveal" | "revive"): Promise<DailyBoosts | null> {
  try {
    const r = await apiFetch("/daily/consume", {
      method: "POST",
      metaReason: "daily-consume",
      skipThrottle: true,
      body: JSON.stringify({ boost_type: boostType }),
    });
    if (!r || typeof r !== "object") return null;
    return r as DailyBoosts;
  } catch {
    return null;
  }
}

export async function dismissDailyBanner(): Promise<DailyBoosts | null> {
  try {
    const r = await apiFetch("/daily/dismiss-banner", { method: "POST", metaReason: "daily-dismiss", skipThrottle: true, body: JSON.stringify({}) });
    if (!r || typeof r !== "object") return null;
    return r as DailyBoosts;
  } catch {
    return null;
  }
}

