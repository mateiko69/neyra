import { trackAnalyticsEvent } from "../analytics";

export type AiAssistType = "opener" | "rewrite";
export type AiAssistMode =
  | "suggest_opener"
  | "playful"
  | "confident"
  | "warm"
  | "polish"
  | "more_natural"
  | "shorter"
  | "flirty"
  | "witty"
  | "charming"
  | "direct"
  | "thoughtful"
  | "tease_lightly";

export type AiAssistThreadState = "empty" | "active";
export type AiAssistDraftState = "empty" | "active";
export type AiAssistSource = "inline_panel" | "composer_button";

export type AiAssistBasePayload = {
  assist_type: AiAssistType;
  mode: AiAssistMode;
  thread_state: AiAssistThreadState;
  draft_state: AiAssistDraftState;
  source: AiAssistSource;
  plan_tier: "free" | "premium" | "premium_plus";
};

export type AiAssistSuggestionIndex = 0 | 1 | 2;

export function threadStateFromMessages(messagesLength: number): AiAssistThreadState {
  return messagesLength === 0 ? "empty" : "active";
}

export function draftStateFromDraft(draft: string): AiAssistDraftState {
  return (draft ?? "").trim() === "" ? "empty" : "active";
}

export async function trackAiAssistRequested(payload: AiAssistBasePayload): Promise<void> {
  await trackAnalyticsEvent("ai_assist_requested", payload);
}

export async function trackAiAssistSuggestionSelected(
  payload: AiAssistBasePayload & { suggestion_index: AiAssistSuggestionIndex },
): Promise<void> {
  await trackAnalyticsEvent("ai_assist_suggestion_selected", payload);
}

export async function trackAiAssistDismissed(payload: AiAssistBasePayload): Promise<void> {
  await trackAnalyticsEvent("ai_assist_dismissed", payload);
}

export async function trackAiAssistEditedAfterInsert(payload: AiAssistBasePayload): Promise<void> {
  await trackAnalyticsEvent("ai_assist_edited_after_insert", payload);
}

export async function trackAiAssistSentAfterUse(payload: AiAssistBasePayload): Promise<void> {
  await trackAnalyticsEvent("ai_assist_sent_after_use", payload);
}

export async function trackAiAssistLimitReached(
  payload: AiAssistBasePayload & {
    assists_left?: number;
  },
): Promise<void> {
  await trackAnalyticsEvent("ai_assist_limit_reached", payload);
}

export async function trackAiAssistUpgradeClicked(
  payload: AiAssistBasePayload & {
    assists_left?: number;
  },
): Promise<void> {
  await trackAnalyticsEvent("ai_assist_upgrade_clicked", payload);
}

