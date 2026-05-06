/**
 * Requires a running API (see playwright.config.ts `webServer` for frontend only).
 *
 * Credentials (recommended):
 * - PLAYWRIGHT_AUTH_EMAIL / PLAYWRIGHT_AUTH_PASSWORD
 * - PLAYWRIGHT_API_URL or API_URL (origin including `/api/v1` suffix or bare origin)
 *
 * Mirrors DEEP_QA_* env fallbacks if unset.
 */

import { devices, test, expect } from "@playwright/test";

function normalizeApiBase(raw: string): string {
  const s = raw.trim().replace(/\/+$/, "");
  return s.endsWith("/api/v1") ? s : `${s}/api/v1`;
}

async function authenticatePage(page: import("@playwright/test").Page): Promise<boolean> {
  const email =
    String(process.env.PLAYWRIGHT_AUTH_EMAIL || process.env.DEEP_QA_EMAIL || "").trim() || "qa_demo_a@neyra.local";
  const password =
    String(process.env.PLAYWRIGHT_AUTH_PASSWORD || process.env.DEEP_QA_PASSWORD || "").trim() || "qa-demo-only";
  const rawApiUrl = String(
    process.env.PLAYWRIGHT_API_URL ||
      process.env.API_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      "http://127.0.0.1:8000/api/v1",
  );
  const apiBase = normalizeApiBase(rawApiUrl);

  let token: string | null = null;
  let loginRes: import("@playwright/test").APIResponse;
  try {
    loginRes = await page.request.post(`${apiBase}/auth/login`, { data: { email, password } });
  } catch {
    return false;
  }
  if (loginRes.ok()) {
    const data = (await loginRes.json().catch(() => null)) as { access_token?: string };
    if (typeof data?.access_token === "string") token = data.access_token;
  }
  if (!token) return false;

  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await page.evaluate((tok: string) => {
    try {
      localStorage.setItem("neyra:token", tok);
      localStorage.setItem("access_token", tok);
      localStorage.setItem("token", tok);
    } catch {
      /* ignore */
    }
  }, token);

  await page.goto("/discover", { waitUntil: "domcontentloaded" });
  await page.waitForURL(/\/(discover|onboarding|login)(\?|$|\/)/, { timeout: 25_000 }).catch(() => {});
  try {
    if (/\/onboarding(\/|$|\?)/.test(new URL(page.url()).pathname)) {
      const skipLink = page.getByRole("link", { name: /skip/i });
      const skipBtn = page.getByRole("button", { name: /skip/i });
      if (await skipLink.count()) await skipLink.first().click();
      else if (await skipBtn.count()) await skipBtn.first().click();
      await page.waitForURL(/\/discover/, { timeout: 20_000 }).catch(() => {});
    }
  } catch {
    /* ignore onboarding guard */
  }
  return true;
}

async function smokeAuthenticatedSurfaces(page: import("@playwright/test").Page): Promise<void> {
  const ok = await authenticatePage(page);
  test.skip(!ok, `Login failed for PLAYWRIGHT_AUTH_EMAIL / PLAYWRIGHT_API_URL (normalized API reachable?)`);

  expect(new URL(page.url()).pathname.endsWith("/login")).toBeFalsy();

  await expect(page.locator("body")).toBeVisible();
  const hero = page.getByTestId("discover-photo").first();
  if (await hero.count()) await expect(hero).toBeVisible({ timeout: 35_000 });

  await page.goto("/matches", { waitUntil: "domcontentloaded" });
  await expect(page.locator("body")).toBeVisible();

  await page.goto("/profile", { waitUntil: "domcontentloaded" });
  await expect(page.locator("body")).toBeVisible();
  await expect(page).toHaveURL(/\/profile/);

  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await expect(page.locator("body")).toBeVisible();
}

test.describe("Authenticated surfaces QA", () => {
  test.describe.configure({ timeout: 120_000 });

  test("desktop: Discover, Matches, Profile, Chat", async ({ page }) => {
    await smokeAuthenticatedSurfaces(page);
  });

  test.describe("mobile viewport", () => {
    test.use({
      viewport: devices["Pixel 7"].viewport,
      isMobile: true,
      hasTouch: true,
    });
    test("mobile: Discover, Matches, Profile, Chat", async ({ page }) => {
      await smokeAuthenticatedSurfaces(page);
    });
  });
});
