import type { I18nText } from "./i18n/message";

const NEXT_PAGE_TOAST_KEY = "neyra:next-page-toast";
const NEXT_PAGE_TOAST_JSON_PREFIX = "json:";

export function queueNextPageToast(message: string | NonNullable<I18nText>): void {
  if (typeof window === "undefined") return;
  if (typeof message === "string") {
    const trimmed = message.trim();
    if (!trimmed) return;
    window.sessionStorage.setItem(NEXT_PAGE_TOAST_KEY, trimmed);
    return;
  }

  const serialized = JSON.stringify(message);
  if (!serialized) return;
  window.sessionStorage.setItem(NEXT_PAGE_TOAST_KEY, `${NEXT_PAGE_TOAST_JSON_PREFIX}${serialized}`);
}

export function consumeNextPageToast(): I18nText {
  if (typeof window === "undefined") return null;
  const message = window.sessionStorage.getItem(NEXT_PAGE_TOAST_KEY) || "";
  if (message) {
    window.sessionStorage.removeItem(NEXT_PAGE_TOAST_KEY);
  }
  if (!message) return null;

  if (message.startsWith(NEXT_PAGE_TOAST_JSON_PREFIX)) {
    try {
      const parsed = JSON.parse(message.slice(NEXT_PAGE_TOAST_JSON_PREFIX.length)) as I18nText;
      if (parsed && typeof parsed === "object") {
        if ("raw" in parsed && typeof parsed.raw === "string") return { raw: parsed.raw };
        if ("key" in parsed && typeof parsed.key === "string") {
          return parsed.vars ? { key: parsed.key, vars: parsed.vars } : { key: parsed.key };
        }
      }
    } catch {
      /* ignore malformed stored payloads */
    }
  }

  return { raw: message };
}
