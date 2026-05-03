import type { PremiumPlusHookContext, PremiumPlusHookPayload } from "./premiumPlusHooks";
import { trackAnalyticsEvent } from "./analytics";

type HookVariant = {
  variant_id: string;
  copy_id: string;
  text: string;
};

const STORAGE_VARIANT_PREFIX = "pp_hook_variant:";
const STORAGE_LAST_SEEN = "pp_hook_last_seen";
const STORAGE_PENDING_ATTR = "pp_hook_pending_attr";
const STORAGE_CONVERTED_ONCE = "pp_hook_converted_once";

const ATTR_WINDOW_MS = 30 * 60 * 1000; // 30 min

const VARIANTS: Record<PremiumPlusHookContext, HookVariant[]> = {
  ai_styles: [
    { variant_id: "a1", copy_id: "ai_styles_unlock_deeper", text: "Unlock deeper AI styles with Premium Plus." },
    { variant_id: "a2", copy_id: "ai_styles_more_personal", text: "Premium Plus unlocks more personal, distinctive AI styles." },
    { variant_id: "a3", copy_id: "ai_styles_best_tones", text: "Get the best tones (witty, flirty, charming) with Premium Plus." },
  ],
  compatibility: [
    { variant_id: "c1", copy_id: "compat_full_reasoning", text: "See full AI compatibility reasoning with Premium Plus." },
    { variant_id: "c2", copy_id: "compat_deeper_insight", text: "Unlock deeper compatibility insights with Premium Plus." },
    { variant_id: "c3", copy_id: "compat_plus_depth", text: "Premium Plus shows the full compatibility breakdown." },
  ],
  recovery: [
    { variant_id: "r1", copy_id: "recovery_more_options", text: "Unlock 3 recovery suggestions with Premium Plus." },
    { variant_id: "r2", copy_id: "recovery_stronger_guidance", text: "Premium Plus gives stronger recovery guidance (more options)." },
  ],
  escalation: [
    { variant_id: "e1", copy_id: "escalation_earlier_timing", text: "Premium Plus surfaces “next step” timing earlier." },
    { variant_id: "e2", copy_id: "escalation_better_timing", text: "Unlock earlier escalation timing with Premium Plus." },
  ],
  coach: [{ variant_id: "k1", copy_id: "coach_placeholder", text: "Unlock deeper coach guidance with Premium Plus." }],
  trust: [{ variant_id: "t1", copy_id: "trust_placeholder", text: "Unlock deeper trust insights with Premium Plus." }],
};

function safeParse<T>(raw: string | null): T | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function storageGet(key: string): string | null {
  try {
    return sessionStorage.getItem(key) ?? localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSetSession(key: string, value: string): void {
  try {
    sessionStorage.setItem(key, value);
  } catch {}
}

function chooseIndex(n: number, salt: string): number {
  // Small deterministic-ish hash from time + salt (session-stable via storage).
  const seed = `${Date.now()}:${Math.random()}:${salt}`;
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  const idx = Math.abs(h) % Math.max(1, n);
  return idx;
}

export function getPremiumPlusHookVariant(context: PremiumPlusHookContext): HookVariant {
  const options = VARIANTS[context] ?? [];
  const fallback: HookVariant = { variant_id: "default", copy_id: "default", text: "Upgrade to Premium Plus." };
  if (!options.length) return fallback;

  const key = `${STORAGE_VARIANT_PREFIX}${context}`;
  const existing = safeParse<HookVariant>(storageGet(key));
  if (existing && typeof existing.variant_id === "string" && typeof existing.text === "string") return existing;

  const idx = chooseIndex(options.length, context);
  const chosen = options[idx] ?? options[0] ?? fallback;
  storageSetSession(key, JSON.stringify(chosen));
  return chosen;
}

export async function trackPremiumPlusHookVariant(payload: PremiumPlusHookPayload & { variant_id: string; copy_id: string }): Promise<void> {
  await trackAnalyticsEvent("premium_plus_hook_variant", payload);
}

export function setLastSeenHook(payload: PremiumPlusHookPayload & { variant_id: string; copy_id: string }): void {
  storageSetSession(
    STORAGE_LAST_SEEN,
    JSON.stringify({
      context: payload.context,
      variant_id: payload.variant_id,
      copy_id: payload.copy_id,
      at_ms: Date.now(),
      plan_tier: payload.plan_tier,
      thread_state: payload.thread_state ?? null,
      surface: payload.surface ?? null,
    }),
  );
}

export function buildSubscriptionHref(context: PremiumPlusHookContext, variant_id: string): string {
  const params = new URLSearchParams();
  params.set("pp_ctx", context);
  params.set("pp_var", variant_id);
  return `/subscription?${params.toString()}`;
}

export async function emitHookAttributionFromUrl(): Promise<void> {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  const ctx = url.searchParams.get("pp_ctx") || "";
  const variant = url.searchParams.get("pp_var") || "";
  if (!ctx || !variant) return;

  const lastSeen = safeParse<any>(storageGet(STORAGE_LAST_SEEN));
  const payload = {
    context: ctx,
    variant_id: variant,
    last_seen_context: lastSeen?.context ?? null,
    last_seen_variant: lastSeen?.variant_id ?? null,
    last_seen_at_ms: lastSeen?.at_ms ?? null,
    at_ms: Date.now(),
  };
  storageSetSession(STORAGE_PENDING_ATTR, JSON.stringify(payload));
  await trackAnalyticsEvent("premium_plus_hook_attribution", payload);
}

export async function maybeEmitHookConverted(plan_tier: "free" | "premium" | "premium_plus"): Promise<void> {
  if (plan_tier !== "premium_plus") return;
  if (typeof window === "undefined") return;
  if (storageGet(STORAGE_CONVERTED_ONCE) === "1") return;
  const pending = safeParse<any>(storageGet(STORAGE_PENDING_ATTR));
  if (!pending) return;
  const at = Number(pending.at_ms ?? 0);
  if (!Number.isFinite(at) || Date.now() - at > ATTR_WINDOW_MS) return;

  storageSetSession(STORAGE_CONVERTED_ONCE, "1");
  await trackAnalyticsEvent("premium_plus_hook_converted", pending);
}

