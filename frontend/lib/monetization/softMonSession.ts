/**
 * Session-scoped gates for soft monetization hints (once per trigger type per tab session).
 */

export type SoftMonKind = "partner_reply" | "match_moment" | "ai_limit";

function key(k: SoftMonKind): string {
  return `neyra:soft_mon:${k}`;
}

/** Returns true the first time this session for `kind`; false afterwards. */
export function softMonClaimOnce(kind: SoftMonKind): boolean {
  try {
    if (typeof sessionStorage === "undefined") return true;
    const k = key(kind);
    if (sessionStorage.getItem(k) === "1") return false;
    sessionStorage.setItem(k, "1");
    return true;
  } catch {
    return true;
  }
}

export function softMonConsumed(kind: SoftMonKind): boolean {
  try {
    return typeof sessionStorage !== "undefined" && sessionStorage.getItem(key(kind)) === "1";
  } catch {
    return false;
  }
}
