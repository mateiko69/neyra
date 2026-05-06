import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

test.describe("Discover demo photos resolve to frontend assets", () => {
  const artifactDir = path.join(process.cwd(), "artifacts", "qa-mvp");

  async function assertImageNotFlatColor(page: import("@playwright/test").Page, selector: string) {
    const variance = await page.locator(selector).first().evaluate(async (node) => {
      const img = node as HTMLImageElement;
      await new Promise<void>((resolve) => {
        if (img.complete) resolve();
        else img.addEventListener("load", () => resolve(), { once: true });
      });
      const w = Math.max(1, Math.min(48, img.naturalWidth || img.width || 1));
      const h = Math.max(1, Math.min(48, img.naturalHeight || img.height || 1));
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d");
      if (!ctx) return 0;
      ctx.drawImage(img, 0, 0, w, h);
      const data = ctx.getImageData(0, 0, w, h).data;
      let sum = 0;
      let sumSq = 0;
      let n = 0;
      for (let i = 0; i < data.length; i += 4) {
        const lum = 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
        sum += lum;
        sumSq += lum * lum;
        n += 1;
      }
      if (n <= 1) return 0;
      const mean = sum / n;
      return Math.max(0, sumSq / n - mean * mean);
    });
    expect(variance).toBeGreaterThan(2);
  }

  test("desktop: demo /demo-profiles url does not rewrite to API", async ({ page }) => {
    fs.mkdirSync(artifactDir, { recursive: true });
    await page.addInitScript(() => {
      localStorage.setItem("neyra:token", "test_token");
      localStorage.setItem("access_token", "test_token");
      localStorage.setItem("token", "test_token");
    });
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
      const req = route.request();
      const url = req.url();
      const method = req.method().toUpperCase();
      const pathname = (() => {
        try {
          return new URL(url).pathname;
        } catch {
          return url;
        }
      })();
      if (method === "GET" && pathname.endsWith("/api/v1/auth/me")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ id: 1, user_id: 1, onboarding_required: false, onboarding_completed: true }),
        });
        return;
      }
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
    await assertImageNotFlatColor(page, '[data-testid="discover-photo"]');
    await page.screenshot({ path: path.join(artifactDir, "discover-desktop.png"), fullPage: false });
  });

  test("mobile viewport: demo /demo-profiles url does not rewrite to API", async ({ page }) => {
    fs.mkdirSync(artifactDir, { recursive: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript(() => {
      localStorage.setItem("neyra:token", "test_token");
      localStorage.setItem("access_token", "test_token");
      localStorage.setItem("token", "test_token");
    });

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
      const req = route.request();
      const url = req.url();
      const method = req.method().toUpperCase();
      const pathname = (() => {
        try {
          return new URL(url).pathname;
        } catch {
          return url;
        }
      })();
      if (method === "GET" && pathname.endsWith("/api/v1/auth/me")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ id: 1, user_id: 1, onboarding_required: false, onboarding_completed: true }),
        });
        return;
      }
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
    await assertImageNotFlatColor(page, '[data-testid="discover-photo"]');
    const cardHost = page.getByTestId("discover-card").first();
    if (await cardHost.count()) {
      const nestedScrollableCount = await cardHost.locator("*").evaluateAll((nodes) => {
        let count = 0;
        for (const node of nodes) {
          const el = node as HTMLElement;
          const cs = window.getComputedStyle(el);
          const canScroll = /(auto|scroll)/.test(cs.overflowY) && el.scrollHeight > el.clientHeight + 2;
          if (canScroll) count += 1;
        }
        return count;
      });
      expect(nestedScrollableCount).toBe(0);
    }
    await page.getByRole("button", { name: /Boost profile/i }).click();
    await expect(page).toHaveURL(/\/premium/);
    await page.screenshot({ path: path.join(artifactDir, "mobile-discover-final.png"), fullPage: false });
  });
});

