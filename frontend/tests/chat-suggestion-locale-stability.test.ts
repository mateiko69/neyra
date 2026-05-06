import assert from "node:assert/strict";
import test from "node:test";
import { getChatFallbackPack } from "../lib/ai/chatFallbackReplies";

function hasCyrillic(value: string): boolean {
  return /[\u0400-\u04FF]/.test(value);
}

test("fallback suggestions keep selected locale copy (EN/ES/PT/ZH)", () => {
  const locales = ["en", "es", "pt", "zh-CN"] as const;
  for (const locale of locales) {
    const pack = getChatFallbackPack(locale);
    const joined = [pack.easySuggestion, pack.flirtySuggestion, pack.deepSuggestion].join(" ");
    if (locale !== "uk" && locale !== "ru") {
      assert.equal(hasCyrillic(joined), false, `${locale} suggestions unexpectedly contain Cyrillic text`);
    }
  }
});

