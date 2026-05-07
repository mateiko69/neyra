import type { ChatBrainSuggestionsResponse } from "./api";

/** In-memory cache for chat-brain responses (not persisted). */
export const CHAT_BRAIN_SUGGESTIONS_CACHE = new Map<string, ChatBrainSuggestionsResponse>();
/** Keyed by `${partnerUserId}:${effectiveSuggestionLocale}` so English cache is not reused after switching to Ukrainian, etc. */
export const CHAT_BRAIN_LAST_GOOD_BY_PARTNER = new Map<string, ChatBrainSuggestionsResponse>();

export function clearChatBrainSuggestionMemoryCaches(): void {
  CHAT_BRAIN_SUGGESTIONS_CACHE.clear();
  CHAT_BRAIN_LAST_GOOD_BY_PARTNER.clear();
}
