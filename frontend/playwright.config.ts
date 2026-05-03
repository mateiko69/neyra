import { defineConfig, devices } from "@playwright/test";

/** Dedicated port so Playwright does not collide with a developer `next dev` on :3000. */
const devPort = process.env.PLAYWRIGHT_DEV_PORT || "3177";
const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://127.0.0.1:${devPort}`;
const reuseExisting = process.env.PLAYWRIGHT_REUSE_SERVER !== "0" && !process.env.CI;

export default defineConfig({
  testDir: "./tests/ui",
  timeout: 120_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    // Avoid `npm run dev` (wipes `.next` each start).
    command: `npx next dev --hostname 127.0.0.1 --port ${devPort}`,
    url: baseURL,
    reuseExistingServer: reuseExisting,
    timeout: 120_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
