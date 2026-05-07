/** In-memory AI dedupe caches. Separate module so locale clears run synchronously without importing heavy `api.ts` (avoids i18n ↔ api cycles). */

export const chatBrainSuggestionsMemo = new Map<string, { at: number; res: unknown }>();
export const chatBrainSuggestionsInflight = new Map<string, Promise<unknown>>();

export const openerSessionMem = new Map<string, unknown>();

export function clearChatBrainSuggestionsDedupeStores(): void {
  chatBrainSuggestionsMemo.clear();
  chatBrainSuggestionsInflight.clear();
}

export function clearOpenerSessionMemoryCache(): void {
  openerSessionMem.clear();
}

export function clearAllAiDedupeStores(): void {
  clearChatBrainSuggestionsDedupeStores();
  clearOpenerSessionMemoryCache();
}
