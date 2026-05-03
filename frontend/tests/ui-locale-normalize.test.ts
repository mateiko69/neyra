import assert from "node:assert/strict";
import test from "node:test";
import { normalizeLocaleInput, SUPPORTED_LOCALE_CODES } from "../lib/i18n/locales";
import { resolveToastPlacement } from "../lib/toastPlacement";

test("normalizeLocaleInput: every supported code round-trips", () => {
  for (const code of SUPPORTED_LOCALE_CODES) {
    assert.equal(normalizeLocaleInput(code), code);
  }
});

test("normalizeLocaleInput: zh-TW aliases", () => {
  assert.equal(normalizeLocaleInput("zh-tw"), "zh-TW");
  assert.equal(normalizeLocaleInput("zh-HK"), "zh-TW");
});

test("normalizeLocaleInput: unknown gibberish", () => {
  assert.equal(normalizeLocaleInput("not-a-real-locale-code-xyz"), null);
});

test("toast placement: login/discover avoid CTA overlap zones", () => {
  assert.equal(resolveToastPlacement("/login"), "top-right");
  assert.equal(resolveToastPlacement("/discover"), "top-right");
});

test("toast placement: onboarding uses header-safe top-center", () => {
  assert.equal(resolveToastPlacement("/onboarding"), "top-center");
});
