import assert from "node:assert/strict";
import test from "node:test";
import { CHAT_FALLBACK_REPLIES } from "../lib/ai/chatFallbackReplies";
import type { AppLocale } from "../lib/i18n/locales";

const EN = CHAT_FALLBACK_REPLIES.en;

/** Locales that previously fell through to English in the runtime fallback map. */
const REGRESSION_LOCALES: AppLocale[] = [
  "es",
  "zh-CN",
  "zh-TW",
  "ko",
  "el",
  "id",
  "ar",
  "he",
  "de",
  "fr",
  "uk",
  "ru",
  "pt",
  "it",
  "pl",
  "tr",
  "ja",
  "hi",
  "vi",
  "th",
  "nl",
  "sv",
  "cs",
  "ro",
  "hu",
  "da",
  "fi",
  "no",
];

function assertPackDiffersFromEnglish(code: AppLocale): void {
  const loc = CHAT_FALLBACK_REPLIES[code];
  const fields: (keyof typeof EN)[] = [
    "easySuggestion",
    "flirtySuggestion",
    "deepSuggestion",
    "easyLabel",
    "flirtyLabel",
    "deepLabel",
    "easyDescription",
    "flirtyDescription",
    "deepDescription",
    "inlineLoading",
    "premiumCta",
  ];
  for (const f of fields) {
    const a = String(EN[f] ?? "").trim();
    const b = String(loc[f] ?? "").trim();
    assert.ok(b.length > 0, `${code}: empty ${String(f)}`);
    assert.notEqual(b, a, `${code}: ${String(f)} still matches English`);
  }
}

test("runtime CHAT_FALLBACK_REPLIES: every app locale has a distinct pack from English", () => {
  for (const code of REGRESSION_LOCALES) {
    assertPackDiffersFromEnglish(code);
  }
});

test("runtime CHAT_FALLBACK_REPLIES: English pack keeps canonical seed copy", () => {
  assert.match(EN.easySuggestion, /Got you/i);
});
