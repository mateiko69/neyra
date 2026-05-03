import assert from "node:assert/strict";
import test from "node:test";
import { resolveChatLanguage, detectMixedScripts, isTextLikelyInExpectedLanguage } from "../lib/chat/aiLanguageTone";

test("resolveChatLanguage: partner native wins", () => {
  const out = resolveChatLanguage(
    { nativeLanguage: "en", additionalLanguages: ["uk"] },
    { nativeLanguage: "uk", additionalLanguages: ["en"] },
    "en",
  );
  assert.equal(out.language, "uk");
  assert.equal(out.reason, "partner_native");
});

test("resolveChatLanguage: shared additional language", () => {
  const out = resolveChatLanguage(
    { nativeLanguage: "uk", additionalLanguages: ["en", "es"] },
    { nativeLanguage: null, additionalLanguages: ["es", "pt"] },
    "en",
  );
  assert.equal(out.language, "es");
  assert.equal(out.reason, "shared");
});

test("resolveChatLanguage: fallback to uiLocale then en", () => {
  const out = resolveChatLanguage(
    { nativeLanguage: null, additionalLanguages: [] },
    { nativeLanguage: null, additionalLanguages: [] },
    "fr",
  );
  assert.equal(out.language, "fr");
  assert.equal(out.reason, "fallback");

  const out2 = resolveChatLanguage(null, null, "xx-YY");
  assert.equal(out2.language, "en");
  assert.equal(out2.reason, "fallback");
});

test("language validator: mixed scripts rejected", () => {
  assert.equal(detectMixedScripts("Hey привіт"), true);
  assert.equal(isTextLikelyInExpectedLanguage("en", "Hey привіт"), false);
});

test("language validator: latin ok, cyrillic ok", () => {
  assert.equal(isTextLikelyInExpectedLanguage("en", "Hey — what caught your eye here?"), true);
  assert.equal(isTextLikelyInExpectedLanguage("uk", "Привіт! Що тебе тут зачепило?"), true);
});

