import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

function detectLang(input: string): "uk" | "en" | "es" {
  const text = String(input || "").trim();
  if (/[іїєґІЇЄҐ]/.test(text)) return "uk";
  if (/[а-яА-ЯёЁ]/.test(text)) return "uk";
  if (/\b(hola|cómo|como estas|gracias)\b/i.test(text)) return "es";
  return "en";
}

test.describe("Mobile AI language consistency", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test("selector + locale consistency + demo language echo", async ({ page }) => {
    const artifacts = path.join(process.cwd(), "artifacts", "qa-mvp");
    fs.mkdirSync(artifacts, { recursive: true });
    const partnerId = 9191;
    const viewerId = 1;
    let serverMessages: any[] = [
      {
        id: 1,
        raw_id: 1,
        sender_id: partnerId,
        receiver_id: viewerId,
        content: "Hello there",
        created_at: new Date().toISOString(),
      },
    ];

    async function expectComposerReady() {
      await expect(page).toHaveURL(new RegExp(`/chat/${partnerId}`));
      await expect(page.getByTestId("chat-composer-input")).toBeVisible({ timeout: 20_000 });
      await expect(page.getByTestId("chat-ai-button")).toBeVisible({ timeout: 20_000 });
      await expect(page.getByTestId("ai-suggestions")).toBeVisible({ timeout: 20_000 });
    }

    async function openAndGenerateSuggestions() {
      await page.getByTestId("chat-ai-button").first().click();
      const generateBtn = page.locator('[data-testid="ai-suggestions"] button').first();
      await expect(generateBtn).toBeVisible({ timeout: 20_000 });
      await generateBtn.click();
      const suggestions = page.locator('[data-testid="ai-suggestions"] .chat-ai__suggestion');
      await expect(suggestions.first()).toBeVisible({ timeout: 20_000 });
      return suggestions;
    }

    await page.route("**/api/v1/**", async (route) => {
      const req = route.request();
      const method = req.method().toUpperCase();
      const url = new URL(req.url());
      const p = url.pathname;

      if (method === "GET" && p.endsWith("/api/v1/auth/me")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ id: viewerId, user_id: viewerId, onboarding_required: false, onboarding_completed: true }),
        });
        return;
      }
      if (method === "GET" && p.endsWith("/api/v1/subscriptions/me")) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ plan_code: "premium", plan: "premium" }) });
        return;
      }
      if (method === "GET" && p.endsWith("/api/v1/nav/badges")) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
        return;
      }
      if (method === "GET" && p.endsWith("/api/v1/messages/conversations")) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
        return;
      }
      if (method === "GET" && p.endsWith("/api/v1/profiles/me")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ user_id: viewerId, display_name: "Viewer", onboarding_completed: true, preferred_language: "uk" }),
        });
        return;
      }
      if (method === "GET" && p.includes(`/api/v1/profiles/partner/${partnerId}`)) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ user_id: partnerId, display_name: "Partner", photo_urls: "/demo-profiles/women/demo_001/main.jpg" }),
        });
        return;
      }
      if (method === "GET" && p.includes(`/api/v1/messages/${partnerId}`)) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ messages: serverMessages, match_id: 22 }) });
        return;
      }
      if (method === "POST" && p.endsWith("/api/v1/ai/chat-brain/suggestions")) {
        const body = req.postDataJSON() as any;
        const locale = String(body?.ai_locale || body?.language || body?.locale || "en").toLowerCase();
        const isUk = locale.startsWith("uk");
        const isEs = locale.startsWith("es");
        const variants = isUk
          ? {
              light: "Привіт! Як минає твій день?",
              flirty: "Ти звучиш цікаво, продовжимо?",
              deep: "Мені подобається твій вайб, що для тебе важливо у стосунках?",
            }
          : isEs
            ? {
                light: "Hola, como va tu dia?",
                flirty: "Me encanta tu energia, seguimos hablando?",
                deep: "Me gusta tu vibra, que valoras en una relacion?",
              }
            : {
                light: "Hey! How is your day going?",
                flirty: "You seem fun, want to keep chatting?",
                deep: "I like your vibe - what matters most to you in a relationship?",
              };
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ok: true,
            variants,
            coaching: { action: "write_now" },
            ui: { suggestions_visible: true },
            recommended_variant: "light",
            recommendation_reason: "fits_context",
            variant_insights: {},
            meta: { mode: "reply", language: isUk ? "uk" : isEs ? "es" : "en", ai_used: true },
          }),
        });
        return;
      }
      if (method === "POST" && p.endsWith("/api/v1/messages")) {
        const body = req.postDataJSON() as any;
        const content = String(body?.content || "").trim();
        const userLang = detectLang(content);
        const botReply =
          userLang === "uk" ? "Привіт! Я теж пишу українською." : userLang === "es" ? "Hola! Te respondo en espanol." : "Hey! I will reply in English.";
        const nextId = (serverMessages.at(-1)?.id ?? 0) + 1;
        const nextBotId = nextId + 1;
        const now = new Date().toISOString();
        serverMessages = [
          ...serverMessages,
          { id: nextId, raw_id: nextId, sender_id: viewerId, receiver_id: partnerId, content, created_at: now },
          { id: nextBotId, raw_id: nextBotId, sender_id: partnerId, receiver_id: viewerId, content: botReply, created_at: now },
        ];
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ok: true, kind: "sent", message: { id: nextId, raw_id: nextId, sender_id: viewerId, receiver_id: partnerId, content, created_at: now } }),
        });
        return;
      }
      if (method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, _mocked: true, path: p }) });
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, _mocked: true, path: p }) });
    });

    await page.addInitScript(() => {
      localStorage.setItem("neyra:token", "test_token_1234567890");
      localStorage.setItem("access_token", "test_token_1234567890");
      localStorage.setItem("token", "test_token_1234567890");
      localStorage.setItem("neyra:auth_storage_version", "1");
      localStorage.setItem("neyra_ai_suggestion_locale", "uk");
      localStorage.setItem("neyra:locale", "en");
    });

    await page.goto("/login", { waitUntil: "domcontentloaded" });
    await page.evaluate(() => localStorage.setItem("neyra:locale", "uk"));
    await page.goto(`/chat/${partnerId}`, { waitUntil: "domcontentloaded" });
    await expectComposerReady();

    await page.locator("select.chat-composer__ai-locale-select").selectOption("uk");
    const suggestions = await openAndGenerateSuggestions();
    await expect(suggestions.first()).toContainText(/Привіт|стосунках|цікаво/i);
    await page.screenshot({ path: path.join(artifacts, "mobile-ai-language-auto-uk.png"), fullPage: false });

    await page.locator("select.chat-composer__ai-locale-select").selectOption("en");
    const enSuggestions = await openAndGenerateSuggestions();
    await expect(enSuggestions.first()).toContainText(/How is your day|keep chatting|relationship/i);
    await page.screenshot({ path: path.join(artifacts, "mobile-ai-language-override-en.png"), fullPage: false });

    await page.evaluate(() => localStorage.setItem("neyra:locale", "en"));
    await page.reload({ waitUntil: "domcontentloaded" });
    await expectComposerReady();
    await page.locator("select.chat-composer__ai-locale-select").selectOption("es");
    const esSuggestions = await openAndGenerateSuggestions();
    await expect(esSuggestions.first()).toContainText(/Hola|vibra|relacion/i);
    await expect.poll(async () => page.evaluate(() => localStorage.getItem("neyra:locale"))).toBe("en");
    await page.screenshot({ path: path.join(artifacts, "mobile-ai-language-override-es.png"), fullPage: false });

    const input = page.getByTestId("chat-composer-input").first();
    await input.fill("Привіт, як справи?");
    await page.getByTestId("chat-send-button").click();
    await page.reload({ waitUntil: "domcontentloaded" });
    await expectComposerReady();
    await expect(page.getByText(/українською/i)).toBeVisible();

    await input.fill("Hey, how are you?");
    await page.getByTestId("chat-send-button").click();
    await page.reload({ waitUntil: "domcontentloaded" });
    await expectComposerReady();
    await expect(page.getByText(/reply in English/i)).toBeVisible();
  });
});
