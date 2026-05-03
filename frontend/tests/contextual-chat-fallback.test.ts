import assert from "node:assert/strict";
import test from "node:test";
import { detectContextualSuggestionBucket, getChatFallbackPackForChatSuggestions } from "../lib/ai/contextualChatFallback";

test("detectContextualSuggestionBucket: UA weekend hint", () => {
  assert.equal(detectContextualSuggestionBucket("ідеальні вихідні для тебе якими б були?"), "weekend");
});

test("getChatFallbackPackForChatSuggestions: uk + weekend overlays suggestions only", () => {
  const pack = getChatFallbackPackForChatSuggestions("uk", "Ок 🙂 як для тебе виглядають ідеальні вихідні?");
  const joined = `${pack.easySuggestion} ${pack.flirtySuggestion} ${pack.deepSuggestion}`.toLowerCase();
  assert.match(joined, /вихідн|релакс|актив|прогулян|каву|видихнути|емоцій/);
  assert.doesNotMatch(joined, /\bwhat\b|\byourself\b|\bgenuinely\b|\bplayful\b|\bweekend\b/i);
  assert.equal(pack.easyLabel, "Легко");
});

test("getChatFallbackPackForChatSuggestions: non-uk unchanged base easySuggestion", () => {
  const pack = getChatFallbackPackForChatSuggestions("en", "weekend plans?");
  assert.match(pack.easySuggestion, /Got you/i);
});
