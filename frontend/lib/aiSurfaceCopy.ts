/**
 * Normalizes AI/system reason strings into stable codes and renders through i18n.
 *
 * CRITICAL: never return hardcoded localized copy here — UI locale must control output.
 */
const INTERNAL_PATTERN =
  /compatibility_score|top_reasons|gating|ai[_\s]?tier|visual_score|vibe_score|symmetry_score|candidate_profile|viewer_profile|batch_result|api[_\s]?/i;

export type DiscoverReasonCode =
  | "same_relationship_goal"
  | "similar_communication_style"
  | "shared_interests"
  | "nearby_city"
  | "verified_profile"
  | "strong_profile_quality"
  | "potential_match";

export function normalizeDiscoverReasonCode(raw: string | null | undefined): DiscoverReasonCode | null {
  const s = String(raw ?? "").trim();
  if (!s) return null;
  if (INTERNAL_PATTERN.test(s)) return null;

  // Already a stable code.
  if (/^[a-z][a-z0-9_]*$/i.test(s) && s.includes("_")) {
    const code = s.toLowerCase();
    if (
      code === "same_relationship_goal" ||
      code === "similar_communication_style" ||
      code === "shared_interests" ||
      code === "nearby_city" ||
      code === "verified_profile" ||
      code === "strong_profile_quality" ||
      code === "potential_match"
    ) {
      return code as DiscoverReasonCode;
    }
  }

  const lower = s.toLowerCase();

  // Legacy backend English phrases (compat engine).
  if (lower.includes("same relationship goal") || lower.includes("relationship goal")) return "same_relationship_goal";
  if (lower.includes("same city")) return "nearby_city";
  if (lower.includes("shared interests") || lower.includes("interests overlap") || lower.includes("similar interests")) return "shared_interests";
  if (lower.includes("potential match")) return "potential_match";
  if (lower.includes("strong profile quality") || lower.includes("profile quality")) return "strong_profile_quality";
  if (lower.includes("easier to start a conversation") || lower.includes("conversation potential") || lower.includes("conversation")) return "similar_communication_style";

  // Legacy hardcoded Ukrainian UI strings (must not leak into EN UI).
  if (s.includes("Ви шукаєте одне й те саме")) return "same_relationship_goal";
  if (s.includes("Схожий стиль спілкування")) return "similar_communication_style";
  if (s.includes("Ви в одному місті")) return "nearby_city";
  if (s.includes("Профіль живий")) return "strong_profile_quality";

  return null;
}

export type TranslateFn = (key: string, vars?: Record<string, string | number>) => string;

export function renderDiscoverReason(raw: string | null | undefined, t: TranslateFn): string {
  const code = normalizeDiscoverReasonCode(raw);
  if (!code) return "";
  const key = `discover.reason.${code}` as const;
  const v = t(key);
  return v && !v.startsWith("discover.reason.") ? v : "";
}

export function pickDiscoverReasons(reasons: string[] | null | undefined, t: TranslateFn, max = 2): string[] {
  const list = Array.isArray(reasons) ? reasons : [];
  const out: string[] = [];
  for (const r of list) {
    const line = renderDiscoverReason(r, t);
    if (line && !out.includes(line)) out.push(line);
    if (out.length >= max) break;
  }
  return out;
}
