import type { ChatBrainSuggestionsResponse } from "./api";

/** In-memory cache for chat-brain responses (not persisted). */
export const CHAT_BRAIN_SUGGESTIONS_CACHE = new Map<string, ChatBrainSuggestionsResponse>();
export const CHAT_BRAIN_LAST_GOOD_BY_PARTNER = new Map<number, ChatBrainSuggestionsResponse>();

export function clearChatBrainSuggestionMemoryCaches(): void {
  CHAT_BRAIN_SUGGESTIONS_CACHE.clear();
  CHAT_BRAIN_LAST_GOOD_BY_PARTNER.clear();
}
