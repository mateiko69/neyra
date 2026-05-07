/**
 * NEYRA_API_CACHE_TEST_HOOKS=1 must be set before `api` module first loads.
 */
process.env.NEYRA_API_CACHE_TEST_HOOKS = "1";

import assert from "node:assert/strict";
import test from "node:test";
import {
  dangerouslyListApiCacheKeysForTests,
  dangerouslySeedApiCacheEntryForTests,
  invalidateApiGetCache,
} from "../lib/api";

test("invalidateApiGetCache('/messages') clears conversation + thread GET keys", () => {
  dangerouslySeedApiCacheEntryForTests("GET:http://example.test/api/v1/messages/conversations", { ok: true });
  dangerouslySeedApiCacheEntryForTests("GET:http://example.test/api/v1/messages/42", { ok: true });
  assert.ok(dangerouslyListApiCacheKeysForTests().length >= 2);
  invalidateApiGetCache("/messages");
  assert.equal(
    dangerouslyListApiCacheKeysForTests().filter((k) => k.includes("/messages")).length,
    0,
  );
});
