import assert from "node:assert/strict";
import test from "node:test";
import { normalizeDiscoverReasonCode } from "../lib/aiSurfaceCopy";

test("normalizeDiscoverReasonCode: legacy Ukrainian strings map to codes", () => {
  assert.equal(normalizeDiscoverReasonCode("Ви шукаєте одне й те саме у стосунках"), "same_relationship_goal");
  assert.equal(normalizeDiscoverReasonCode("Схожий стиль спілкування — легко почати розмову"), "similar_communication_style");
});

test("normalizeDiscoverReasonCode: legacy English phrases map to codes", () => {
  assert.equal(normalizeDiscoverReasonCode("Same relationship goal"), "same_relationship_goal");
  assert.equal(normalizeDiscoverReasonCode("Strong profile quality, easier to start a conversation"), "strong_profile_quality");
  assert.equal(normalizeDiscoverReasonCode("Potential match with good conversation potential"), "potential_match");
});

test("normalizeDiscoverReasonCode: unknown localized string is rejected (prevents mixed-language leaks)", () => {
  assert.equal(normalizeDiscoverReasonCode("якась випадкова причина"), null);
});

