import { apiFetch } from "../api";
import { logAiData, logAiGate } from "../aiDebug";
import { getStoredLocale } from "../i18n";

export type CompatibilityLevel = "low" | "medium" | "high";

export type CompatibilityScore = {
  score: number;
  level: CompatibilityLevel;
  reasons: string[];
  visual_score: number | null;
  vibe_score: number | null;
  symmetry_score: number | null;
  available: boolean;
};

export type CompatibilityBatchResult = CompatibilityScore & { candidate_profile_id: number };

export async function fetchCompatibilityScore(options: {
  viewerProfileId: number;
  candidateProfileId: number;
}): Promise<CompatibilityScore | null> {
  try {
    const raw = await apiFetch("/ai/compatibility-score", {
      method: "POST",
      metaReason: "ai-compatibility-score",
      body: JSON.stringify({
        viewer_profile_id: options.viewerProfileId,
        candidate_profile_id: options.candidateProfileId,
        locale: getStoredLocale(),
      }),
      skipThrottle: true,
    });
    logAiData("ai/compatibility-score", raw);
    if (!raw || typeof raw !== "object") return null;
    const score = Number((raw as any).score ?? 0);
    const levelRaw = String((raw as any).level ?? "medium") as CompatibilityLevel;
    const level: CompatibilityLevel = levelRaw === "low" || levelRaw === "high" ? levelRaw : "medium";
    const reasonsRaw = (raw as any).reasons;
    const reasons = Array.isArray(reasonsRaw) ? reasonsRaw.map((x: any) => String(x ?? "").trim()).filter(Boolean).slice(0, 3) : [];
    const visual = (raw as any).visual_score;
    const vibe = (raw as any).vibe_score;
    const symmetry = (raw as any).symmetry_score;
    return {
      score: Number.isFinite(score) ? Math.max(0, Math.min(100, Math.round(score))) : 0,
      level,
      reasons,
      visual_score: Number.isFinite(Number(visual)) ? Math.round(Number(visual)) : null,
      vibe_score: Number.isFinite(Number(vibe)) ? Math.round(Number(vibe)) : null,
      symmetry_score: Number.isFinite(Number(symmetry)) ? Math.round(Number(symmetry)) : null,
      available: Boolean((raw as any).available),
    };
  } catch (error) {
    logAiGate("ai/compatibility-score", {
      viewerProfileId: options.viewerProfileId,
      candidateProfileId: options.candidateProfileId,
      error: error instanceof Error ? error.message : String(error),
    });
    return null;
  }
}

export async function fetchCompatibilityScoresBatch(options: {
  viewerProfileId: number;
  candidateProfileIds: number[];
}): Promise<Map<number, CompatibilityScore>> {
  try {
    const ids = (Array.isArray(options.candidateProfileIds) ? options.candidateProfileIds : [])
      .map((x) => Math.trunc(Number(x)))
      .filter((x) => Number.isFinite(x) && x > 0)
      .slice(0, 25);
    if (!ids.length) return new Map();
    const raw = await apiFetch("/ai/compatibility-score/batch", {
      method: "POST",
      metaReason: "ai-compatibility-score-batch",
      body: JSON.stringify({
        viewer_profile_id: options.viewerProfileId,
        candidate_profile_ids: ids,
        locale: getStoredLocale(),
      }),
      skipThrottle: true,
    });
    logAiData("ai/compatibility-score/batch", raw);
    const resultsRaw = raw && typeof raw === "object" ? (raw as any).results : null;
    const list: any[] = Array.isArray(resultsRaw) ? resultsRaw : [];
    const out = new Map<number, CompatibilityScore>();
    for (const row of list) {
      const cid = Math.trunc(Number(row?.candidate_profile_id ?? 0));
      if (!Number.isFinite(cid) || cid < 1) continue;
      const score = Number(row?.score ?? 0);
      const levelRaw = String(row?.level ?? "medium") as CompatibilityLevel;
      const level: CompatibilityLevel = levelRaw === "low" || levelRaw === "high" ? levelRaw : "medium";
      const reasonsRaw = row?.reasons;
      const reasons = Array.isArray(reasonsRaw) ? reasonsRaw.map((x: any) => String(x ?? "").trim()).filter(Boolean).slice(0, 3) : [];
      const visual = row?.visual_score;
      const vibe = row?.vibe_score;
      const symmetry = row?.symmetry_score;
      out.set(cid, {
        score: Number.isFinite(score) ? Math.max(0, Math.min(100, Math.round(score))) : 0,
        level,
        reasons,
        visual_score: Number.isFinite(Number(visual)) ? Math.round(Number(visual)) : null,
        vibe_score: Number.isFinite(Number(vibe)) ? Math.round(Number(vibe)) : null,
        symmetry_score: Number.isFinite(Number(symmetry)) ? Math.round(Number(symmetry)) : null,
        available: Boolean(row?.available),
      });
    }
    return out;
  } catch (error) {
    logAiGate("ai/compatibility-score/batch", {
      viewerProfileId: options.viewerProfileId,
      candidateProfileIds: options.candidateProfileIds,
      error: error instanceof Error ? error.message : String(error),
    });
    return new Map();
  }
}
