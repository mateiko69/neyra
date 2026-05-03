/**
 * Background API resilience: softFail must not throw on outages/aborts (no Next overlay).
 */
import assert from "node:assert/strict";
import test from "node:test";

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("apiFetch softFail resolves undefined when fetch fails (network)", async () => {
  globalThis.fetch = async () => {
    throw new TypeError("Failed to fetch");
  };
  const { apiFetch, invalidateApiGetCache } = await import("../lib/api");
  invalidateApiGetCache();
  const out = await apiFetch("/__test/softfail-network", {
    method: "GET",
    softFail: true,
    skipThrottle: true,
    skipCache: true,
    metaReason: "test-softfail",
  });
  assert.equal(out, undefined);
});

test("apiFetch softFail resolves undefined when request is already aborted", async () => {
  const { apiFetch, invalidateApiGetCache } = await import("../lib/api");
  invalidateApiGetCache();
  const ac = new AbortController();
  ac.abort();
  const out = await apiFetch("/__test/softfail-abort", {
    method: "GET",
    softFail: true,
    skipThrottle: true,
    skipCache: true,
    signal: ac.signal,
    metaReason: "test-abort",
  });
  assert.equal(out, undefined);
});

test("fetchTimedReplies returns empty fallback when API soft-fails", async () => {
  globalThis.fetch = async () => {
    throw new TypeError("Failed to fetch");
  };
  const { invalidateApiGetCache } = await import("../lib/api");
  const { fetchTimedReplies } = await import("../lib/chat/api");
  invalidateApiGetCache();
  const r = await fetchTimedReplies({
    messages: [{ role: "them" as const, text: "Hi" }],
    nudgeType: "now",
    partnerUserId: 1,
  });
  assert.equal(r.options.length, 0);
  assert.equal(r.source, "fallback");
});
