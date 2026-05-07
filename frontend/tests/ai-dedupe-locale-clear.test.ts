import assert from "node:assert/strict";
import test from "node:test";
import { stableChatBrainMemoKey } from "../lib/chat/api";
import { clearAllAiDedupeStores, chatBrainSuggestionsMemo, openerSessionMem } from "../lib/chat/aiDedupeStores";

test("clearAllAiDedupeStores wipes in-memory AI memo/opener maps on locale switch simulation", () => {
  chatBrainSuggestionsMemo.set("k", { at: Date.now(), res: { ok: true } });
  openerSessionMem.set("op", { suggestions: [] });
  clearAllAiDedupeStores();
  assert.equal(chatBrainSuggestionsMemo.size, 0);
  assert.equal(openerSessionMem.size, 0);
});

test("stableChatBrainMemoKey includes locale/language so caches do not cross FR ↔ PT reuse", () => {
  const frBody: Record<string, unknown> = {
    partner_user_id: 101,
    mode: "reply_hints",
    tone: "auto",
    locale: "fr",
    language: "fr",
    conversation_mode: "easy",
    ai_locale: "auto",
    language_hint: "fr",
  };
  const ptBody: Record<string, unknown> = { ...frBody, locale: "pt", language: "pt", language_hint: "pt" };
  assert.notEqual(stableChatBrainMemoKey(frBody), stableChatBrainMemoKey(ptBody));
});
