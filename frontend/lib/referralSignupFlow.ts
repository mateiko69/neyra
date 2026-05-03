/** Session flags: signup page → OAuth callback → post-signup referral modal (one path, no auto-share). */

export const SIGNUP_FLOW_SESSION_KEY = "neyra:signup_flow";
export const PENDING_POST_SIGNUP_REFERRAL_KEY = "neyra:pending_post_signup_referral";

export function markSignupFlowFromSignupPage(): void {
  try {
    sessionStorage.setItem(SIGNUP_FLOW_SESSION_KEY, "1");
  } catch {
    /* private mode */
  }
}

/** Call after OAuth token is stored, before navigation. */
export function promoteSignupFlowToPendingReferralModal(): void {
  try {
    if (sessionStorage.getItem(SIGNUP_FLOW_SESSION_KEY) === "1") {
      sessionStorage.setItem(PENDING_POST_SIGNUP_REFERRAL_KEY, "1");
      sessionStorage.removeItem(SIGNUP_FLOW_SESSION_KEY);
    }
  } catch {
    /* */
  }
}

export function clearPendingPostSignupReferral(): void {
  try {
    sessionStorage.removeItem(PENDING_POST_SIGNUP_REFERRAL_KEY);
  } catch {
    /* */
  }
}

export function isPendingPostSignupReferral(): boolean {
  try {
    return sessionStorage.getItem(PENDING_POST_SIGNUP_REFERRAL_KEY) === "1";
  } catch {
    return false;
  }
}

export function postSignupReferralSkipStorageKey(userId: string | number): string {
  return `neyra:post_signup_referral_skip_${userId}`;
}
