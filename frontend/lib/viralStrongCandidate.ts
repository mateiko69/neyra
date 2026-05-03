/**
 * “Strong” AI moments eligible for a soft viral share prompt (not every suggestion).
 */

import type { AiAssistMode } from "./chat/aiAssistAnalytics";
import type { ChatBrainMode, ChatBrainVariantKey } from "./chat/api";

export type ViralAiInsertion =
  | { kind: "openers"; text: string; mode: AiAssistMode }
  | { kind: "rewrite"; text: string; mode: AiAssistMode }
  | {
      kind: "chat_brain";
      text: string;
      brain_mode: ChatBrainMode;
      variant: ChatBrainVariantKey;
      was_recommended?: boolean;
      conversation_stage?: string | null;
      conversation_mode?: string | null;
    }
  | { kind: "timed_reply"; text: string; style: string; index: number }
  | { kind: "first_message"; text: string; variant: string; wasRecommended: boolean }
  | { kind: "meeting"; text: string; meetingKind: string }
  | { kind: "revive"; text: string; style: string; index: number };

export function isStrongAiForViral(ai: ViralAiInsertion): boolean {
  switch (ai.kind) {
    case "chat_brain":
      return Boolean(ai.was_recommended);
    case "timed_reply":
      return ai.index === 0;
    case "first_message":
      return Boolean(ai.wasRecommended);
    case "meeting":
      return ai.meetingKind !== "custom";
    case "revive":
      return ai.index === 0;
    case "openers":
    case "rewrite":
      return String(ai.text || "").trim().length >= 52;
    default:
      return false;
  }
}
