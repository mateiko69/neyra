import assert from "node:assert/strict";
import test from "node:test";
import {
  getAuthMeSnapshot,
  invalidateAuthBootstrapCache,
  parseAuthMeSnapshot,
  primeAuthBootstrapFromMe,
} from "../lib/auth/bootstrap";
import { isPublicAppPath, normalizeAppPath } from "../lib/auth/routes";
import { hasValidTokenShape } from "../lib/auth/session";

test("hasValidTokenShape rejects empty / too short", () => {
  assert.equal(hasValidTokenShape(""), false);
  assert.equal(hasValidTokenShape("   "), false);
  assert.equal(hasValidTokenShape("short"), false);
});

test("hasValidTokenShape accepts JWT-shaped tokens", () => {
  const jwt =
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XwpLQXnYdZ3c6d7G3z8E";
  assert.equal(hasValidTokenShape(jwt), true);
});

test("hasValidTokenShape accepts long opaque bearer", () => {
  assert.equal(hasValidTokenShape("a".repeat(20)), true);
});

test("isPublicAppPath: spec routes and no self-loop confusion", () => {
  assert.equal(isPublicAppPath("/"), true);
  assert.equal(isPublicAppPath("/login"), true);
  assert.equal(isPublicAppPath("/login/"), true);
  assert.equal(isPublicAppPath("/intro"), true);
  assert.equal(isPublicAppPath("/signup"), true);
  assert.equal(isPublicAppPath("/auth/social/callback"), true);
  assert.equal(isPublicAppPath("/discover"), false);
  assert.equal(isPublicAppPath("/onboarding"), false);
  assert.equal(isPublicAppPath("/profile"), false);
});

test("normalizeAppPath strips query", () => {
  assert.equal(normalizeAppPath("/login?next=/discover"), "/login");
});

test("parseAuthMeSnapshot: incomplete onboarding", () => {
  const s = parseAuthMeSnapshot({
    user_id: 42,
    onboarding_required: true,
    onboarding_completed: false,
  });
  assert.equal(s?.user_id, 42);
  assert.equal(s?.onboarding_required, true);
  assert.equal(s?.onboarding_completed, false);
});

test("parseAuthMeSnapshot: completed forces onboarding_required false", () => {
  const s = parseAuthMeSnapshot({
    user_id: 42,
    onboarding_required: true,
    onboarding_completed: true,
  });
  assert.equal(s?.onboarding_required, false);
  assert.equal(s?.onboarding_completed, true);
});

test("primeAuthBootstrapFromMe updates getAuthMeSnapshot for route guard", () => {
  invalidateAuthBootstrapCache();
  primeAuthBootstrapFromMe({ user_id: 7, onboarding_required: false });
  const s = getAuthMeSnapshot();
  assert.equal(s?.user_id, 7);
  assert.equal(s?.onboarding_required, false);
});
