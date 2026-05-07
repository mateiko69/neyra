import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { DISCOVER_SWIPE_DEDUPE_MS, acquireDiscoverSwipe, clearDiscoverSwipeGuard, releaseDiscoverSwipe } from "../lib/discoverSwipeGuard";

test("discover swipe guard blocks duplicate candidate/action within DISCOVER_SWIPE_DEDUPE_MS", () => {
  clearDiscoverSwipeGuard();
  const t0 = 1_000;
  assert.equal(acquireDiscoverSwipe(42, "like", t0), true);
  assert.equal(acquireDiscoverSwipe(42, "like", t0 + 10), false);
  releaseDiscoverSwipe(42, "like");
  const stillInside = t0 + DISCOVER_SWIPE_DEDUPE_MS - 1;
  const justOutside = t0 + DISCOVER_SWIPE_DEDUPE_MS;
  assert.equal(acquireDiscoverSwipe(42, "like", stillInside), false);
  assert.equal(acquireDiscoverSwipe(42, "like", justOutside), true);
  releaseDiscoverSwipe(42, "like");
});

test("discover page handles 429 by showing a toast and pausing auto refill", () => {
  const src = fs.readFileSync(path.join(process.cwd(), "app", "(main)", "discover", "page.tsx"), "utf8");
  assert.match(src, /e instanceof RateLimitError/);
  assert.match(src, /setToast\(t\("errors\.api\.rateLimited"\)\)/);
  assert.match(src, /setSwipeRefreshPaused\(true\)/);
  assert.match(src, /!swipeRefreshPaused && next\.length <= 4/);
});
