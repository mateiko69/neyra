import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

test.describe("Discover demo photos resolve to frontend assets", () => {
  const artifactDir = path.join(process.cwd(), "artifacts", "mobile-hotfix");

  test("desktop: demo /demo-profiles url does not rewrite to API", async ({ page }) => {
    fs.mkdirSync(artifactDir, { recursive: true });
    // Mock discover feed with a demo profile that uses bundled assets.
    await page.route("**/api/v1/discover/feed**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          profiles: [
            {
              user_id: 999,
              display_name: "Demo",
              age: 28,
              city: "Kyiv",
              is_demo_profile: true,
              gender: "woman",
              photo_urls: "/demo-profiles/women/demo_001/main.jpg",
            },
          ],
        }),
      });
    });
    await page.route("**/api/v1/**", async (route) => {
      // Best-effort: prevent auth redirects for this surface test.
      if (route.request().method().toUpperCase() === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
    });

    await page.goto("/discover", { waitUntil: "domcontentloaded" });
    const img = page.getByTestId("discover-photo").first();
    if (await img.count()) {
      const src = await img.getAttribute("src");
      expect(src || "").toMatch(/^\/demo-profiles\/women\/demo_001\/main\.jpg/);
      expect(src || "").not.toMatch(/api\.getneyra\.app\/demo-profiles/i);
    }
    await page.screenshot({ path: path.join(artifactDir, "discover-desktop.png"), fullPage: false });
  });

  test("mobile viewport: demo /demo-profiles url does not rewrite to API", async ({ page }) => {
    fs.mkdirSync(artifactDir, { recursive: true });
    await page.setViewportSize({ width: 390, height: 844 });

    await page.route("**/api/v1/discover/feed**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          profiles: [
            {
              user_id: 1000,
              display_name: "Demo",
              age: 29,
              city: "Lviv",
              is_demo_profile: true,
              gender: "man",
              photo_urls: "/demo-profiles/men/demo_001/main.jpg",
            },
          ],
        }),
      });
    });
    await page.route("**/api/v1/**", async (route) => {
      if (route.request().method().toUpperCase() === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
    });

    await page.goto("/discover", { waitUntil: "domcontentloaded" });
    const img = page.getByTestId("discover-photo").first();
    if (await img.count()) {
      const src = await img.getAttribute("src");
      expect(src || "").toMatch(/^\/demo-profiles\/men\/demo_001\/main\.jpg/);
      expect(src || "").not.toMatch(/api\.getneyra\.app\/demo-profiles/i);
    }
    await page.screenshot({ path: path.join(artifactDir, "discover-mobile.png"), fullPage: false });
  });
});

