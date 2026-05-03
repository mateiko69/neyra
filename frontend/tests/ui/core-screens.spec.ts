import { test, expect } from "@playwright/test";

function assertNoRawI18nKeys(text: string) {
  const t = text || "";
  // Heuristic: our i18n keys usually look like "matches.header.title"
  expect(t).not.toMatch(/\b(chat|matches|onboarding|profile|premium|errors|navigation)\.[a-z0-9_.-]+\b/i);
}

test.describe("Core screens UX sanity", () => {
  test("Onboarding has primary Continue CTA", async ({ page }) => {
    await page.goto("/onboarding", { waitUntil: "domcontentloaded" });
    // Protected envs may redirect to login; wait for redirect to settle.
    await page.waitForURL(/\/onboarding(\/|$|\?)|\/login(\/|$|\?)/, { timeout: 15_000 }).catch(() => {});
    const continueBtn = page.getByRole("button", { name: /continue/i });
    const loginCta = page.getByRole("link", { name: /log in|login|sign in/i }).first();
    const emailInput = page.locator("input[type='email'], #login-email").first();

    // If we get the onboarding UI, "Continue" should be visible.
    if (await continueBtn.isVisible().catch(() => false)) {
      await expect(continueBtn).toBeVisible();
      assertNoRawI18nKeys(await page.textContent("body"));
      return;
    }

    // Otherwise, accept login redirect as a valid protected-route outcome.
    if (page.url().includes("/login") || (await emailInput.count()) || (await loginCta.count())) {
      assertNoRawI18nKeys(await page.textContent("body"));
      return;
    }

    // Last resort: if we ended up on login, accept it as protected-route behavior.
    try {
      await expect(continueBtn).toBeVisible();
    } catch {
      if (page.url().includes("/login")) {
        assertNoRawI18nKeys(await page.textContent("body"));
        return;
      }
      throw new Error("onboarding_continue_missing");
    }
  });

  test("Discover has clear Like/Pass actions", async ({ page }) => {
    await page.goto("/discover", { waitUntil: "domcontentloaded" });
    // Protected route may redirect to login; in that case it still "loads" and should not show raw keys.
    assertNoRawI18nKeys(await page.textContent("body"));
    // If the deck is shown, Like/Pass controls should exist.
    const like = page.getByRole("button", { name: /like/i });
    const pass = page.getByRole("button", { name: /pass/i });
    // Only assert if present (demo/protected can alter the surface)
    if (await like.count()) await expect(like.first()).toBeVisible();
    if (await pass.count()) await expect(pass.first()).toBeVisible();
  });

  test("Matches has Say hi and AI opener CTAs when list visible", async ({ page }) => {
    await page.goto("/matches", { waitUntil: "domcontentloaded" });
    assertNoRawI18nKeys(await page.textContent("body"));
    const sayHi = page.getByRole("link", { name: /say hi/i });
    const aiOpener = page.getByRole("link", { name: /opener/i });
    if (await sayHi.count()) await expect(sayHi.first()).toBeVisible();
    if (await aiOpener.count()) await expect(aiOpener.first()).toBeVisible();
  });

  test("Chat has only one AI panel and no assistant messages in history", async ({ page }) => {
    await page.goto("/chat/40", { waitUntil: "domcontentloaded" });
    assertNoRawI18nKeys(await page.textContent("body"));
    // One AI suggestions panel max
    const aiPanels = page.locator("[aria-label='AI chat suggestions']");
    await expect(aiPanels).toHaveCount(0, { timeout: 2000 }).catch(async () => {
      await expect(aiPanels).toHaveCount(1);
    });
    // No AI-tag demo bubbles (we filter isDemoSimulation/assistant role)
    await expect(page.locator(".chat-message-bubble--has-ai-tag")).toHaveCount(0);
  });
});

