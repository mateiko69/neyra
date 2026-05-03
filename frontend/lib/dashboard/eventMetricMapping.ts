export type MetricKey =
  | "ai_usage_rate"
  | "ai_success_reply_received_rate"
  | "ai_success_readiness_improved_rate"
  | "ai_success_recovery_worked_rate"
  | "ai_success_escalation_progressed_rate"
  | "pp_hook_ctr"
  | "pp_hook_conversion_rate"
  | "pp_hook_best_context"
  | "pp_hook_best_variant";

/**
 * Single-source mapping of emitted events → dashboard metrics.
 *
 * Notes:
 * - This v1 dashboard is frontend-only. It reads a local buffer populated by `trackAnalyticsEvent`.
 * - Server-side analytics emitted purely on the backend (e.g. some trust events) may not appear here.
 */
export const EVENT_MAPPING: Record<string, string> = {
  // Growth funnel (client)
  landing_view: "Funnel: landing view",
  signup_started: "Funnel: signup started",
  signup_completed: "Funnel: signup completed",
  review_prompt_shown: "Review: prompt shown",
  review_positive_clicked: "Review: positive (Play Store)",
  review_feedback_opened: "Review: feedback form opened",
  signup_from_share: "Funnel: signup from viral/referral share link",
  viral_share_prompt_shown: "Viral: share prompt shown (strong AI send)",
  share_clicked: "Viral: share CTA clicked",
  share_sent: "Viral: share completed (native / social / clipboard)",
  onboarding_completed: "Funnel: onboarding completed",
  discover_viewed: "Funnel: discover viewed",
  like_sent: "Funnel: like sent",
  match_created: "Funnel: match created",
  chat_opened: "Funnel: chat opened",
  ai_limit_hit: "Funnel: AI limit hit",
  paywall_shown: "Funnel: paywall shown (impression)",
  paywall_opened: "Funnel: paywall opened (modal/surface)",
  paywall_cta_clicked: "Funnel: paywall primary CTA (upgrade / trial / continue)",
  paywall_clicked: "Funnel: paywall entry click (navigate to premium)",
  premium_purchased: "Funnel: premium purchased",
  conversion_after_reply: "Funnel: conversion after partner reply moment",
  conversion_after_match: "Funnel: conversion after match moment",
  reengagement_return_prompt: "Retention: return after idle",
  reengagement_like_notification: "Retention: incoming-like toast",
  reengagement_match_notification: "Retention: new match toast",
  reengagement_chat_activity: "Retention: chat heating up toast",
  reengagement_chat_revive_hint: "Retention: AI revive suggested",

  // AI assist baseline usage
  ai_assist_requested: "AI usage (requests)",
  ai_assist_suggestion_selected: "AI usage (suggestion selected)",
  ai_assist_sent_after_use: "AI-assisted send",

  // AI effectiveness / habit loop success
  ai_assist_success_reply_received: "Success: reply received after AI-assisted send",
  ai_assist_success_readiness_improved: "Success: readiness improved after AI usage",
  ai_assist_success_recovery_worked: "Success: recovery led to continued chat",
  ai_assist_success_escalation_progressed: "Success: escalation led to continued exchange",

  // Premium Plus hook optimization
  premium_plus_hook_context: "Plus hook context",
  premium_plus_hook_variant: "Plus hook variant exposure",
  premium_plus_hook_seen: "Plus hook seen",
  premium_plus_hook_clicked: "Plus hook clicked",
  premium_plus_hook_attribution: "Subscription page arrived from hook",
  premium_plus_hook_converted: "Converted to Plus within attribution window",

  // Trust (frontend-visible)
  trust_badge_seen: "Trust badge seen",
  trust_badge_clicked: "Trust badge clicked",
  verified_profile_clicked: "Verified profile clicked",
  verified_vs_unverified_conversion: "Verified vs unverified swipe conversion signal",
};

