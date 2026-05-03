/** Capture ?ref= / ?referral= for signup, OAuth, and POST /referrals/claim. */

const STORAGE_KEY = "neyra:pending_referral_code";

export function captureReferralCodeFromLocation(): void {
  if (typeof window === "undefined") return;
  try {
    const params = new URLSearchParams(window.location.search);
    const ref = (params.get("ref") || params.get("referral") || "").trim();
    if (ref) sessionStorage.setItem(STORAGE_KEY, ref.slice(0, 32).toUpperCase());
  } catch {
    /* ignore */
  }
}

export function peekPendingReferralCode(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const v = sessionStorage.getItem(STORAGE_KEY);
    return v && v.trim() ? v.trim() : null;
  } catch {
    return null;
  }
}

export function clearPendingReferralCode(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}
