import { clearAllAiDedupeStores } from "./chat/aiDedupeStores";

const AI_CACHE_PREFIXES = [
  "neyra:ai_openers:v1:",
  "neyra:ai_reply_options:",
  "neyra:ai_timed_replies:",
  "neyra:ai_improve_reply:",
  "neyra:ai_chat_brain:",
  "neyra:ai_coach:",
  "neyra:ai_readiness:",
] as const;

function clearFromStorage(storage: Storage) {
  const keys: string[] = [];
  for (let i = 0; i < storage.length; i += 1) {
    const k = storage.key(i);
    if (!k) continue;
    if (AI_CACHE_PREFIXES.some((p) => k.startsWith(p))) keys.push(k);
  }
  keys.forEach((k) => storage.removeItem(k));
}

/** Clear only AI suggestion caches (does not touch auth/app caches). */
export function clearAiSuggestionCaches() {
  if (typeof window === "undefined") return;
  clearAllAiDedupeStores();
  void import("./chat/chatBrainSuggestionsCache")
    .then((m) => {
      if (typeof m.clearChatBrainSuggestionMemoryCaches === "function") m.clearChatBrainSuggestionMemoryCaches();
    })
    .catch(() => {});
  try {
    clearFromStorage(sessionStorage);
  } catch {
    // ignore
  }
  try {
    clearFromStorage(localStorage);
  } catch {
    // ignore
  }
}

