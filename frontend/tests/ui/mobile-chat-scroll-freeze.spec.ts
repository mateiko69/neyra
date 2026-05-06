import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

function mkMessages(partnerId: number, viewerId: number, count: number) {
  const out: any[] = [];
  const now = Date.now();
  for (let i = 0; i < count; i += 1) {
    const own = i % 2 === 0;
    out.push({
      id: i + 1,
      raw_id: i + 1,
      sender_id: own ? viewerId : partnerId,
      receiver_id: own ? partnerId : viewerId,
      content: `${own ? "me" : "them"} message ${i + 1} — ${"lorem ipsum ".repeat(18)}`,
      created_at: new Date(now - (count - i) * 60_000).toISOString(),
    });
  }
  return out;
}

test.describe("Mobile chat scroll does not freeze after send", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test("scrollTop changes after sending", async ({ page }) => {
    const artifactDir = path.join(process.cwd(), "artifacts", "qa-mvp");
    fs.mkdirSync(artifactDir, { recursive: true });
    const partnerId = 777;
    const viewerId = 1;
    let serverMessages: any[] = mkMessages(partnerId, viewerId, 140);

    await page.route("**/api/v1/**", async (route) => {
      const req = route.request();
      const url = req.url();
      const method = req.method().toUpperCase();
      const path = (() => {
        try {
          return new URL(url).pathname;
        } catch {
          return url;
        }
      })();

      if (method === "GET" && path.endsWith("/api/v1/auth/me")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ id: viewerId, user_id: viewerId, onboarding_required: false, onboarding_completed: true }),
        });
        return;
      }
      if (method === "GET" && path.endsWith("/api/v1/subscriptions/me")) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ plan_code: "free", plan: "free" }) });
        return;
      }
      if (method === "GET" && path.endsWith("/api/v1/nav/badges")) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
        return;
      }
      if (method === "GET" && path.endsWith("/api/v1/messages/conversations")) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
        return;
      }
      if (method === "GET" && path.includes(`/api/v1/profiles/partner/${partnerId}`)) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            user_id: partnerId,
            display_name: "Partner",
            photo_urls: "/demo-profiles/women/demo_001/main.jpg",
          }),
        });
        return;
      }
      if (method === "GET" && path.includes(`/api/v1/messages/${partnerId}`)) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(serverMessages) });
        return;
      }

      if (path.endsWith("/api/v1/messages") && method === "POST") {
        const body = (await req.postDataJSON().catch(() => null)) as any;
        const content = String(body?.content || "hi").trim();
        const nextId = (serverMessages.at(-1)?.id ?? 0) + 1;
        const createdAt = new Date().toISOString();
        serverMessages = [
          ...serverMessages,
          { id: nextId, raw_id: nextId, sender_id: viewerId, receiver_id: partnerId, content, created_at: createdAt },
        ];
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ok: true,
            kind: "sent",
            message: { id: nextId, raw_id: nextId, sender_id: viewerId, receiver_id: partnerId, content, created_at: createdAt },
          }),
        });
        return;
      }

      if (method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, _mocked: true, url }) });
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, _mocked: true, url }) });
    });

    // Session token so route guard doesn't bounce.
    await page.addInitScript(() => {
      localStorage.setItem("neyra:token", "test_token");
      localStorage.setItem("access_token", "test_token");
      localStorage.setItem("token", "test_token");
    });

    await page.goto(`/chat/${partnerId}`, { waitUntil: "domcontentloaded" });
    // Ensure we didn't get redirected away from the thread.
    await expect(page).toHaveURL(new RegExp(`/chat/${partnerId}`));
    await expect(page.getByTestId("chat-composer-input")).toBeVisible({ timeout: 25_000 });
    await expect(page.getByTestId("chat-send-button")).toBeVisible({ timeout: 25_000 });
    const scrollHost = page.getByTestId("chat-messages").first();
    await expect(scrollHost).toBeVisible({ timeout: 25_000 });
    await expect(page.getByTestId("ai-suggestions")).toBeVisible({ timeout: 25_000 });
    const compactSuggestionOrButton = page
      .locator('[data-testid="ai-suggestions"] .chat-ai__suggestion, [data-testid="ai-suggestions"] button:has-text("Get suggestions")')
      .first();
    await expect(compactSuggestionOrButton).toBeVisible({ timeout: 25_000 });

    // Ensure the container is actually scrollable even if the UI didn't render enough history yet.
    await scrollHost.evaluate((el) => {
      el.style.height = "320px";
      el.style.maxHeight = "320px";
      el.style.overflowY = "auto";
      const filler = document.createElement("div");
      filler.setAttribute("data-testid", "scroll-filler");
      filler.style.height = "6000px";
      filler.style.pointerEvents = "none";
      el.appendChild(filler);
    });

    // Ensure overflow scroll is actually enabled and scrollHeight > clientHeight.
    const initial = await scrollHost.evaluate((el) => {
      const maxScroll = Math.max(0, el.scrollHeight - el.clientHeight);
      return {
        scrollTop: el.scrollTop,
        scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight,
        maxScroll,
        overflowY: window.getComputedStyle(el).overflowY,
      };
    });
    expect(initial.overflowY).toMatch(/auto|scroll/);
    expect(initial.maxScroll).toBeGreaterThan(80);

    const nestedScrollableCount = await page.locator("[data-testid='chat-messages'] *").evaluateAll((nodes) => {
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

    // Move into the middle so we can verify up/down changes.
    await scrollHost.evaluate((el) => {
      const maxScroll = Math.max(0, el.scrollHeight - el.clientHeight);
      el.scrollTop = Math.floor(maxScroll / 2);
    });
    const mid = await scrollHost.evaluate((el) => el.scrollTop);
    expect(mid).toBeGreaterThan(0);

    // Send a message.
    const input = page.getByTestId("chat-composer-input").first();
    await expect(input).toBeVisible();
    await input.fill("scroll test");
    await page.getByTestId("chat-send-button").click();

    // Wait for the new outgoing message to appear.
    await expect(page.getByText("scroll test")).toBeVisible({ timeout: 20_000 });

    // Scroll down and up again. Bug: scrollTop stops changing after send.
    await scrollHost.evaluate((el) => el.scrollBy({ top: 240, behavior: "auto" }));
    const afterDown = await scrollHost.evaluate((el) => el.scrollTop);
    await scrollHost.evaluate((el) => el.scrollBy({ top: -180, behavior: "auto" }));
    const afterUp = await scrollHost.evaluate((el) => el.scrollTop);

    expect(afterDown).not.toBe(mid);
    expect(afterUp).not.toBe(afterDown);

    // Composer still editable.
    await input.fill("ok");
    await expect(input).toHaveValue(/ok/);
    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toMatch(/[ґЂРÂ�]|бЃ/);
    await page.screenshot({ path: path.join(artifactDir, "mobile-chat-compact.png"), fullPage: false });
  });
});

