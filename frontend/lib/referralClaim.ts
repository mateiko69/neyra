import { apiFetch, getToken } from "./api";
import { clearPendingReferralCode, peekPendingReferralCode } from "./referralCapture";

/** After login/signup, attach pending ?ref= to the account when valid. */
export async function tryConsumePendingReferralClaim(): Promise<void> {
  if (typeof window === "undefined" || !getToken()) return;
  const code = peekPendingReferralCode();
  if (!code) return;
  try {
    await apiFetch("/referrals/claim", {
      method: "POST",
      body: JSON.stringify({ referral_code: code }),
      metaReason: "referrals:claim",
      skipThrottle: true,
    });
  } catch {
    /* Invalid or duplicate referral — do not block auth. */
  } finally {
    clearPendingReferralCode();
  }
}
