import assert from "node:assert/strict";
import test from "node:test";
import { stableChatBrainMemoKey } from "../lib/chat/api";

test("stableChatBrainMemoKey ignores object key order", () => {
  const a = stableChatBrainMemoKey({
    partner_user_id: 3,
    mode: "auto",
    tone: "auto",
    language: "uk",
    language_hint: null as unknown as string | null,
    conversation_mode: "easy",
  });
  const b = stableChatBrainMemoKey({
    conversation_mode: "easy",
    language: "uk",
    language_hint: null as unknown as string | null,
    mode: "auto",
    partner_user_id: 3,
    tone: "auto",
  });
  assert.equal(a, b);
});
