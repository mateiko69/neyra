import { apiFetch } from "../api";
import { logAiData, logAiGate } from "../aiDebug";

export type TrustLevel = "low" | "medium" | "high";
export type ProfileTrust = { trust_score: number; trust_level: TrustLevel; is_verified: boolean };

const trustClientTtlMs = 10_000;
const trustClientCache = new Map<number, { at: number; value: ProfileTrust | null }>();

export async function fetchProfileTrust(options: { userId?: number } = {}): Promise<ProfileTrust | null> {
  const cacheKey = options.userId != null && Number.isFinite(options.userId) ? Math.trunc(options.userId) : 0;
  const now = Date.now();
  const hit = trustClientCache.get(cacheKey);
  if (hit && now - hit.at < trustClientTtlMs) return hit.value;

  try {
    const qs = options.userId ? `?user_id=${encodeURIComponent(String(options.userId))}` : "";
    const raw = await apiFetch(`/profile/trust${qs}`, { metaReason: "profile-trust" });
    logAiData("profile/trust", raw);
    if (!raw || typeof raw !== "object") return null;
    const score = Number((raw as any).trust_score ?? 0);
    const levelRaw = String((raw as any).trust_level ?? "low") as TrustLevel;
    const trust_level: TrustLevel = levelRaw === "high" || levelRaw === "medium" ? levelRaw : "low";
    const parsed: ProfileTrust = {
      trust_score: Number.isFinite(score) ? Math.max(0, Math.min(100, Math.round(score))) : 0,
      trust_level,
      is_verified: Boolean((raw as any).is_verified),
    };
    trustClientCache.set(cacheKey, { at: Date.now(), value: parsed });
    return parsed;
  } catch (error) {
    logAiGate("profile/trust", {
      userId: options.userId ?? null,
      error: error instanceof Error ? error.message : String(error),
    });
    return null;
  }
}
