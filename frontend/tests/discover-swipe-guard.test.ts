import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { acquireDiscoverSwipe, clearDiscoverSwipeGuard, releaseDiscoverSwipe } from "../lib/discoverSwipeGuard";

test("discover swipe guard blocks duplicate candidate/action within 1.5s", () => {
  clearDiscoverSwipeGuard();
  assert.equal(acquireDiscoverSwipe(42, "like", 1_000), true);
  assert.equal(acquireDiscoverSwipe(42, "like", 1_010), false);
  releaseDiscoverSwipe(42, "like");
  assert.equal(acquireDiscoverSwipe(42, "like", 2_499), false);
  assert.equal(acquireDiscoverSwipe(42, "like", 2_501), true);
  releaseDiscoverSwipe(42, "like");
});

test("discover page handles 429 by showing a toast and pausing auto refill", () => {
  const src = fs.readFileSync(path.join(process.cwd(), "app", "discover", "page.tsx"), "utf8");
  assert.match(src, /e instanceof RateLimitError/);
  assert.match(src, /setToast\(t\("errors\.api\.rateLimited"\)\)/);
  assert.match(src, /setSwipeRefreshPaused\(true\)/);
  assert.match(src, /!swipeRefreshPaused && cards\.length <= 4/);
});
