/**
 * Smart Google Play review prompts: positive moments only, tight caps, never nag rated users.
 */

const SESSION_SHOWN_KEY = "neyra:review_prompt_session_shown";
const SNOOZE_UNTIL_KEY = "neyra:review_prompt_snooze_until";
const BRAIN_INSERT_COUNT_KEY = "neyra:session_ai_brain_inserts";
const USER_RATED_KEY = "neyra:review_user_rated_store";
const FIRST_APP_USE_TS_KEY = "neyra:review_first_app_use_ts";
const ONBOARDING_DONE_TS_KEY = "neyra:review_onboarding_completed_ts";
const LAST_PROMPT_AT_KEY = "neyra:review_last_prompt_at_ms";
const LIFETIME_SUCCESS_CHATS_KEY = "neyra:review_lifetime_success_chats";
const SESSION_REAL_AI_KEY = "neyra:review_session_real_ai";
const SESSION_BLOCK_ERROR_KEY = "neyra:review_session_block_error";

const COOLDOWN_DAYS_MS = 4 * 24 * 60 * 60 * 1000;
const POST_ONBOARDING_COOLDOWN_MS = 48 * 60 * 60 * 1000;
const FIRST_SESSION_BLOCK_MS = 2 * 60 * 60 * 1000;

/** @deprecated use snoozeReviewPromptCooldown */
const TWO_DAYS_MS = 2 * 24 * 60 * 60 * 1000;

export function getAiBrainInsertSessionCount(): number {
  if (typeof sessionStorage === "undefined") return 0;
  try {
    const n = Number(sessionStorage.getItem(BRAIN_INSERT_COUNT_KEY) || "0");
    return Number.isFinite(n) && n >= 0 ? n : 0;
  } catch {
    return 0;
  }
}

/** Returns new total after increment. */
export function bumpAiBrainInsertSessionCount(): number {
  if (typeof sessionStorage === "undefined") return 0;
  try {
    const next = getAiBrainInsertSessionCount() + 1;
    sessionStorage.setItem(BRAIN_INSERT_COUNT_KEY, String(next));
    markReviewSessionRealAiUsed();
    return next;
  } catch {
    return 0;
  }
}

export function markReviewSessionRealAiUsed(): void {
  if (typeof sessionStorage === "undefined") return;
  try {
    sessionStorage.setItem(SESSION_REAL_AI_KEY, "1");
  } catch {
    /* ignore */
  }
}

export function isReviewSessionRealAiUsed(): boolean {
  if (typeof sessionStorage === "undefined") return false;
  try {
    return sessionStorage.getItem(SESSION_REAL_AI_KEY) === "1";
  } catch {
    return false;
  }
}

export function markReviewSessionChatError(): void {
  if (typeof sessionStorage === "undefined") return;
  try {
    sessionStorage.setItem(SESSION_BLOCK_ERROR_KEY, "1");
  } catch {
    /* ignore */
  }
}

export function isReviewSessionBlockedByError(): boolean {
  if (typeof sessionStorage === "undefined") return false;
  try {
    return sessionStorage.getItem(SESSION_BLOCK_ERROR_KEY) === "1";
  } catch {
    return false;
  }
}

/** First authenticated visit to main app surfaces — not intro/onboarding/login. */
export function markAppFirstUseNow(): void {
  if (typeof localStorage === "undefined") return;
  try {
    if (localStorage.getItem(FIRST_APP_USE_TS_KEY)) return;
    localStorage.setItem(FIRST_APP_USE_TS_KEY, String(Date.now()));
  } catch {
    /* ignore */
  }
}

export function getFirstAppUseTs(): number {
  if (typeof localStorage === "undefined") return 0;
  try {
    const n = Number(localStorage.getItem(FIRST_APP_USE_TS_KEY) || "0");
    return Number.isFinite(n) && n > 0 ? n : 0;
  } catch {
    return 0;
  }
}

export function daysSinceFirstAppUse(): number {
  const t0 = getFirstAppUseTs();
  if (!t0) return 0;
  return Math.floor((Date.now() - t0) / (24 * 60 * 60 * 1000));
}

export function markOnboardingCompletedTimestamp(): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(ONBOARDING_DONE_TS_KEY, String(Date.now()));
  } catch {
    /* ignore */
  }
}

export function isWithinPostOnboardingCooldown(): boolean {
  if (typeof localStorage === "undefined") return false;
  try {
    const raw = localStorage.getItem(ONBOARDING_DONE_TS_KEY);
    if (!raw) return false;
    const t = Number(raw);
    if (!Number.isFinite(t)) return false;
    return Date.now() - t < POST_ONBOARDING_COOLDOWN_MS;
  } catch {
    return false;
  }
}

export function isWithinFirstHoursOfAppUse(hours: number = 2): boolean {
  const t0 = getFirstAppUseTs();
  if (!t0) return true;
  return Date.now() - t0 < hours * 60 * 60 * 1000;
}

export function userHasRatedInStore(): boolean {
  if (typeof localStorage === "undefined") return false;
  try {
    return localStorage.getItem(USER_RATED_KEY) === "1";
  } catch {
    return false;
  }
}

export function markUserRatedApp(): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(USER_RATED_KEY, "1");
  } catch {
    /* ignore */
  }
}

export function getLifetimeSuccessChats(): number {
  if (typeof localStorage === "undefined") return 0;
  try {
    const n = Number(localStorage.getItem(LIFETIME_SUCCESS_CHATS_KEY) || "0");
    return Number.isFinite(n) && n >= 0 ? Math.min(99, n) : 0;
  } catch {
    return 0;
  }
}

/** Partner replied after AI-assisted send, or other “successful chat” heuristic. */
export function bumpLifetimeSuccessChats(): number {
  if (typeof localStorage === "undefined") return 0;
  try {
    const next = getLifetimeSuccessChats() + 1;
    localStorage.setItem(LIFETIME_SUCCESS_CHATS_KEY, String(next));
    return next;
  } catch {
    return 0;
  }
}

export function getLastReviewPromptAt(): number {
  if (typeof localStorage === "undefined") return 0;
  try {
    const n = Number(localStorage.getItem(LAST_PROMPT_AT_KEY) || "0");
    return Number.isFinite(n) && n > 0 ? n : 0;
  } catch {
    return 0;
  }
}

export function markReviewPromptShownTimestamp(): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(LAST_PROMPT_AT_KEY, String(Date.now()));
  } catch {
    /* ignore */
  }
}

export function isOutsideRepeatPromptCooldown(): boolean {
  const last = getLastReviewPromptAt();
  if (!last) return true;
  return Date.now() - last >= COOLDOWN_DAYS_MS;
}

export function hasMinimumMaturityForReview(): boolean {
  const days = daysSinceFirstAppUse();
  const life = getLifetimeSuccessChats();
  if (days >= 3) return true;
  if (life >= 2) return true;
  if (days >= 1 && life >= 1) return true;
  return false;
}

export function hasReviewPromptShownThisSession(): boolean {
  if (typeof sessionStorage === "undefined") return true;
  try {
    return sessionStorage.getItem(SESSION_SHOWN_KEY) === "1";
  } catch {
    return true;
  }
}

export function markReviewPromptShownThisSession(): void {
  if (typeof sessionStorage === "undefined") return;
  try {
    sessionStorage.setItem(SESSION_SHOWN_KEY, "1");
  } catch {
    /* ignore */
  }
}

export function isReviewPromptSnoozed(): boolean {
  if (typeof localStorage === "undefined") return false;
  try {
    const raw = localStorage.getItem(SNOOZE_UNTIL_KEY);
    if (!raw) return false;
    const until = Number(raw);
    if (!Number.isFinite(until)) return false;
    return Date.now() < until;
  } catch {
    return false;
  }
}

/** Snooze after neutral / negative / dismiss — a few days. */
export function snoozeReviewPromptCooldown(): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(SNOOZE_UNTIL_KEY, String(Date.now() + COOLDOWN_DAYS_MS));
  } catch {
    /* ignore */
  }
}

/** @deprecated prefer snoozeReviewPromptCooldown */
export function snoozeReviewPromptForTwoDays(): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(SNOOZE_UNTIL_KEY, String(Date.now() + TWO_DAYS_MS));
  } catch {
    /* ignore */
  }
}

export type SmartReviewTrigger = "brain_insert" | "first_message_ai" | "partner_reply_ai";

export function shouldOfferSmartReviewPrompt(opts: {
  trigger: SmartReviewTrigger;
  aiBrainInsertCount: number;
  firstMessageJustSent: boolean;
}): boolean {
  if (userHasRatedInStore()) return false;
  if (hasReviewPromptShownThisSession()) return false;
  if (isReviewPromptSnoozed()) return false;
  if (isReviewSessionBlockedByError()) return false;
  if (isWithinPostOnboardingCooldown()) return false;
  if (!isOutsideRepeatPromptCooldown()) return false;

  const firstTs = getFirstAppUseTs();
  if (!firstTs) return false;

  if (opts.trigger === "partner_reply_ai") {
    if (isWithinFirstHoursOfAppUse(2)) return false;
    return true;
  }

  if (isWithinFirstHoursOfAppUse(2)) return false;

  if (opts.trigger === "brain_insert") {
    if (!isReviewSessionRealAiUsed()) return false;
    if (opts.aiBrainInsertCount < 2) return false;
    return hasMinimumMaturityForReview();
  }

  if (opts.trigger === "first_message_ai") {
    if (!opts.firstMessageJustSent) return false;
    return hasMinimumMaturityForReview() && opts.aiBrainInsertCount >= 1;
  }

  return false;
}

export function defaultAndroidPackageId(): string {
  return (typeof process !== "undefined" && process.env.NEXT_PUBLIC_ANDROID_PACKAGE_ID) || "com.neyra.app";
}

export function googlePlayStoreWebUrl(packageId: string = defaultAndroidPackageId()): string {
  return `https://play.google.com/store/apps/details?id=${encodeURIComponent(packageId)}`;
}

export function isLikelyAndroidTouchPhone(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  return /Android/i.test(ua) && /Mobile/i.test(ua);
}

export function openFeedbackFormUrl(): void {
  const feedbackUrl = (typeof process !== "undefined" ? process.env.NEXT_PUBLIC_FEEDBACK_URL : "")?.trim() || "";
  try {
    if (feedbackUrl) {
      if (feedbackUrl.startsWith("/")) {
        window.location.assign(feedbackUrl);
        return;
      }
      window.open(feedbackUrl, "_blank", "noopener,noreferrer");
      return;
    }
    window.location.assign("/profile?source=review_feedback");
  } catch {
    /* ignore */
  }
}

/**
 * Primary CTA: Play Store on Android (market intent), otherwise web listing / copy.
 */
export async function openReviewPrimaryAction(opts?: {
  feedbackUrl?: string | null;
  onCopied?: () => void;
  onOpenedFallback?: () => void;
}): Promise<void> {
  const pkg = defaultAndroidPackageId();
  const playWeb = googlePlayStoreWebUrl(pkg);

  if (isLikelyAndroidTouchPhone()) {
    try {
      window.location.href = `market://details?id=${encodeURIComponent(pkg)}`;
    } catch {
      /* ignore */
    }
    window.setTimeout(() => {
      try {
        window.open(playWeb, "_blank", "noopener,noreferrer");
      } catch {
        /* ignore */
      }
    }, 450);
    return;
  }

  let copied = false;
  try {
    await navigator.clipboard.writeText(playWeb);
    copied = true;
    opts?.onCopied?.();
  } catch {
    copied = false;
  }

  if (!copied) {
    try {
      window.open(playWeb, "_blank", "noopener,noreferrer");
      opts?.onOpenedFallback?.();
    } catch {
      /* ignore */
    }
  }
}
