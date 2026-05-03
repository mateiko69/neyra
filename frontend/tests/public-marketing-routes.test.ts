import assert from "node:assert/strict";
import test from "node:test";
import { isPublicAppPath } from "../lib/auth/routes";

test("marketing and legal routes are public (no auth redirect)", () => {
  const paths = ["/", "/premium", "/privacy", "/terms", "/refund", "/contact"];
  for (const p of paths) {
    assert.equal(isPublicAppPath(p), true, `${p} should be public`);
  }
});

test("auth-required surfaces remain protected", () => {
  assert.equal(isPublicAppPath("/discover"), false);
  assert.equal(isPublicAppPath("/chat"), false);
});
