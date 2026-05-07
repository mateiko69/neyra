import assert from "node:assert/strict";
import test from "node:test";
import { clearAllAiDedupeStores, chatBrainSuggestionsMemo, openerSessionMem } from "../lib/chat/aiDedupeStores";

test("clearAllAiDedupeStores wipes in-memory AI memo/opener maps on locale switch simulation", () => {
  chatBrainSuggestionsMemo.set("k", { at: Date.now(), res: { ok: true } });
  openerSessionMem.set("op", { suggestions: [] });
  clearAllAiDedupeStores();
  assert.equal(chatBrainSuggestionsMemo.size, 0);
  assert.equal(openerSessionMem.size, 0);
});
