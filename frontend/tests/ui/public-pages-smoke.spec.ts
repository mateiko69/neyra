import { test, expect } from "@playwright/test";

/** Paddle-facing public routes: visible anchors for automated smoke checks. */
const cases: { path: string; expectText: RegExp }[] = [
  { path: "/", expectText: /NEYRA/i },
  { path: "/premium", expectText: /Plans for every pace/i },
  { path: "/privacy", expectText: /Privacy Policy/i },
  { path: "/terms", expectText: /Terms of Service/i },
  { path: "/refund", expectText: /Refund Policy/i },
  { path: "/contact", expectText: /support@neyra\.app/i },
];

test.describe("Public pages smoke (Paddle)", () => {
  for (const { path, expectText } of cases) {
    test(`${path} renders expected content`, async ({ page }) => {
      const res = await page.goto(path, { waitUntil: "domcontentloaded" });
      expect(res?.status(), `${path} HTTP status`).toBeLessThan(400);
      await expect(page).not.toHaveURL(/\/login(\?|$)/);

      if (path === "/") {
        await page.waitForSelector('[data-testid="neyra-i18n-root"]', { timeout: 30_000 });
      }

      await expect(page.locator("body")).toContainText(expectText);

      if (path !== "/") {
        await expect(page.getByRole("navigation", { name: /marketing/i })).toBeVisible();
        await expect(page.locator("footer.public-marketing-footer")).toContainText(/Privacy Policy/i);
      } else {
        await expect(page.getByRole("contentinfo")).toContainText(/Privacy Policy/i);
      }
    });
  }
});
