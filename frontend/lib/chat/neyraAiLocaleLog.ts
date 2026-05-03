/** Dev-only logs for AI locale + suggested replies (structured console.info). */

const isProd = typeof process !== "undefined" && process.env.NODE_ENV === "production";

export function neyraAiLocaleDevLog(message: string, payload?: Record<string, unknown>): void {
  if (isProd) return;
  if (typeof console === "undefined" || typeof console.info !== "function") return;
  if (payload && Object.keys(payload).length) {
    console.info("[neyra-ai-locale]", message, payload);
  } else {
    console.info("[neyra-ai-locale]", message);
  }
}

/** Exact strings requested for runtime debugging. */
export function neyraAiLocaleChanged(locale: string): void {
  if (isProd) return;
  console.info("[neyra-ai-locale] locale changed", locale);
}

export function neyraAiLocaleClearingSuggestedRepliesCache(): void {
  if (isProd) return;
  console.info("[neyra-ai-locale] clearing suggested replies cache");
}

export function neyraAiLocaleRequestingSuggestions(payload: { locale: string; threadId: number | null }): void {
  if (isProd) return;
  console.info("[neyra-ai-locale] requesting suggestions", payload);
}

export function neyraAiLocaleRenderedSuggestions(payload: {
  locale: string;
  source: "ai" | "fallback" | "mixed" | "fallback_quota";
}): void {
  if (isProd) return;
  console.info("[neyra-ai-locale] rendered suggestions", payload);
}

/** Dev-only: structured log when inline / bar suggestions render or load. */
export function neyraChatSuggestionDevLog(payload: {
  component: string;
  endpoint: string;
  locale: string | null | undefined;
  source: string;
  fallback: boolean;
  last_message_preview: string;
}): void {
  if (isProd) return;
  if (typeof console === "undefined" || typeof console.info !== "function") return;
  console.info("[neyra-chat-suggestions]", payload);
}
