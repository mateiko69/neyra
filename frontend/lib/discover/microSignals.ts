export const DISCOVER_HOOK_MAX_WORDS = 6;

/** Subset of discover card fields used for micro-signals (keeps this module import-cycle free). */
export type MicroSignalsCardInput = {
  top_reasons?: string[];
  bio?: string;
  interests?: string[];
  city?: string;
  last_active_at?: string | null;
  active_today?: boolean | null;
};

/** Trim to at most `max` words for on-card micro copy. */
export function clampHookWords(text: string, max: number = DISCOVER_HOOK_MAX_WORDS): string {
  const words = String(text || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!words.length) return "";
  return words.slice(0, max).join(" ");
}

/**
 * Short “AI-style” hook from profile signals (deterministic; no network).
 * Prefers curated reasons, then bio snippet, interest, city.
 */
export function buildDiscoverMicroHook(card: MicroSignalsCardInput, surfaceReasons: string[]): string {
  /** Use translated surface reasons only — raw API codes like `strong_profile_quality` must not appear as visible copy. */
  const tryReasons = [...surfaceReasons.map((s) => String(s))];
  for (const raw of tryReasons) {
    const s = raw.replace(/[""«»]/g, "").trim();
    if (!s) continue;
    const clipped = clampHookWords(s);
    if (clipped) return clipped;
  }

  const bio = String(card.bio || "").trim();
  if (bio) {
    const cleaned = bio.replace(/[^\p{L}\p{N}\s'-]/gu, " ");
    const clipped = clampHookWords(cleaned);
    if (clipped) return clipped;
  }

  const interest = (card.interests || []).find((x) => String(x).trim());
  if (interest) return clampHookWords(String(interest).trim());

  const city = String(card.city || "").trim();
  if (city) return clampHookWords(`Near ${city}`);

  return "";
}

export type DiscoverReplySpeed = "fast" | "slow";

/**
 * Heuristic reply-speed signal from activity (not real message metrics).
 */
export function discoverReplySpeedTone(card: MicroSignalsCardInput): DiscoverReplySpeed | null {
  if (Boolean(card.active_today)) return "fast";
  const ts = String(card.last_active_at || "").trim();
  if (!ts) return null;
  const ms = Date.parse(ts);
  if (!Number.isFinite(ms)) return null;
  const hours = (Date.now() - ms) / 3_600_000;
  if (hours <= 6) return "fast";
  return "slow";
}
