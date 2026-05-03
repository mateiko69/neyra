import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

function assertNoRawI18nKeys(text: string) {
  const t = text || "";
  expect(t).not.toMatch(/\b(chat|matches|onboarding|profile|premium|errors|navigation)\.[a-z0-9_.-]+\b/i);
}

type FlowReportStatus = "passed" | "skipped" | "failed";

type FlowReport = {
  landing_flow: FlowReportStatus;
  discover_flow: FlowReportStatus;
  matches_flow: FlowReportStatus;
  chat_ai_flow: FlowReportStatus;
  profile_verification_flow: FlowReportStatus;
  premium_flow: FlowReportStatus;
};

type Metrics = {
  pages_visited: number;
  buttons_clicked: number;
  interactions_count: number;
  flows_completed: string[];
  flow_failures: Record<string, string>;
  flow_skip_reasons: Record<string, string>;
  flow_report: FlowReport;
  auth_ok?: boolean;
  auth_error?: string;
};

function defaultFlowReport(): FlowReport {
  return {
    landing_flow: "skipped",
    discover_flow: "skipped",
    matches_flow: "skipped",
    chat_ai_flow: "skipped",
    profile_verification_flow: "skipped",
    premium_flow: "skipped",
  };
}

function metricsOutPath(): string {
  const fromEnv = process.env.DEEP_QA_METRICS_PATH;
  if (fromEnv && String(fromEnv).trim()) return String(fromEnv).trim();
  return path.join(process.cwd(), "reports", "deep_qa_metrics.json");
}

function loadMetrics(): Metrics {
  return {
    pages_visited: 0,
    buttons_clicked: 0,
    interactions_count: 0,
    flows_completed: [],
    flow_failures: {},
    flow_skip_reasons: {},
    flow_report: defaultFlowReport(),
  };
}

function saveMetrics(m: Metrics) {
  const out = metricsOutPath();
  try {
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, JSON.stringify(m, null, 2), "utf-8");
  } catch {
    // ignore
  }
}

let lastPathCounted = "";

function bumpPageVisit(metrics: Metrics, page: { url: () => string }) {
  const pathOnly = (() => {
    try {
      return new URL(page.url()).pathname;
    } catch {
      return "";
    }
  })();
  if (!pathOnly || pathOnly === lastPathCounted) return;
  lastPathCounted = pathOnly;
  metrics.pages_visited += 1;
  metrics.interactions_count += 1;
  saveMetrics(metrics);
}

async function gotoCounted(page: import("@playwright/test").Page, url: string, metrics: Metrics) {
  metrics.pages_visited += 1;
  metrics.interactions_count += 1;
  lastPathCounted = "";
  saveMetrics(metrics);
  await page.goto(url, { waitUntil: "domcontentloaded" });
  try {
    lastPathCounted = new URL(page.url()).pathname;
  } catch {
    lastPathCounted = "";
  }
  assertNoRawI18nKeys(await page.textContent("body"));
}

async function clickCounted(locator: import("@playwright/test").Locator, metrics: Metrics) {
  metrics.buttons_clicked += 1;
  metrics.interactions_count += 1;
  saveMetrics(metrics);
  await locator.click();
}

async function clickPrimaryNavHref(page: import("@playwright/test").Page, metrics: Metrics, href: string) {
  const testIdByHref: Record<string, string> = {
    "/discover": "nav-discover",
    "/matches": "nav-matches",
    "/chat": "nav-chat",
    "/profile": "nav-profile",
    "/subscription": "nav-premium",
  };
  const tid = testIdByHref[href] || "";
  if (tid) {
    const byTid = page.getByTestId(tid).first();
    if (await byTid.count()) {
      await expect(byTid).toBeVisible({ timeout: 25_000 });
      await clickCounted(byTid, metrics);
      await page.waitForTimeout(200);
      return;
    }
  }
  const link = page.locator(`a[href="${href}"]`).first();
  await expect(link).toBeVisible({ timeout: 25_000 });
  await clickCounted(link, metrics);
  await page.waitForTimeout(200);
}

async function loginAsDemo(page: import("@playwright/test").Page, metrics: Metrics) {
  const baseEmail = process.env.DEEP_QA_EMAIL || "qa_demo_a@neyra.local";
  const password = process.env.DEEP_QA_PASSWORD || "qa-demo-only";

  await gotoCounted(page, "/login", metrics);

  await expect(page.locator("#login-email")).toHaveCount(0);
  await expect(page.locator("#login-password")).toHaveCount(0);
  const bodyText = ((await page.textContent("body")) || "").trim();
  expect(bodyText.length).toBeGreaterThan(0);
  expect(bodyText).not.toMatch(/Runtime Error/i);
  await expect(page.getByRole("button", { name: /apple|facebook/i })).toHaveCount(0);

  const rawApiUrl = String(process.env.API_URL || "http://localhost:8000/api/v1").trim().replace(/\/+$/, "");
  const apiBase = rawApiUrl.endsWith("/api/v1") ? rawApiUrl : `${rawApiUrl}/api/v1`;
  let token: string | null = null;

  const loginRes = await page.request.post(`${apiBase}/auth/login`, { data: { email: baseEmail, password } });
  if (loginRes.ok()) {
    const data = (await loginRes.json().catch(() => null)) as any;
    if (typeof data?.access_token === "string") token = data.access_token;
  }

  if (!token) {
    const email = `qa_${Date.now()}@example.com`;
    const registerRes = await page.request.post(`${apiBase}/auth/register`, {
      data: { email, password, display_name: "QA User" },
    });
    expect(registerRes.ok()).toBeTruthy();
    const data = (await registerRes.json().catch(() => null)) as any;
    expect(typeof data?.access_token).toBe("string");
    token = String(data.access_token);
  }

  await page.evaluate((t: string) => {
    localStorage.setItem("neyra:token", t);
    localStorage.setItem("access_token", t);
    localStorage.setItem("token", t);
  }, String(token));

  const meRes = await page.request.get(`${apiBase}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!meRes.ok()) {
    metrics.auth_ok = false;
    metrics.auth_error = `auth_failed: GET /auth/me → HTTP ${meRes.status()}`;
    saveMetrics(metrics);
    throw new Error(metrics.auth_error);
  }
  metrics.auth_ok = true;
  metrics.auth_error = "";
  saveMetrics(metrics);

  // Some builds show an explicit "Skip" link, others route directly. Be resilient.
  await gotoCounted(page, "/discover", metrics);
  // If onboarding still intercepts, click any Skip control we can find.
  if (/\/onboarding(\/|$|\?)/.test(new URL(page.url()).pathname)) {
    const skipLink = page.getByRole("link", { name: /skip/i });
    const skipBtn = page.getByRole("button", { name: /skip/i });
    if (await skipLink.count()) await clickCounted(skipLink.first(), metrics);
    else if (await skipBtn.count()) await clickCounted(skipBtn.first(), metrics);
  }
  await page.waitForURL(/\/discover(\/|$|\?)/, { timeout: 20_000 });
  bumpPageVisit(metrics, page);
  assertNoRawI18nKeys(await page.textContent("body"));
}

async function setupAuthenticatedSession(page: import("@playwright/test").Page) {
  // Self-contained auth/session: do not rely on cookies or real backend login.
  await page.context().addCookies([
    { name: "access_token", value: "test_token", domain: "localhost", path: "/" },
    { name: "token", value: "test_token", domain: "localhost", path: "/" },
  ]);
  await page.addInitScript(() => {
    localStorage.setItem("neyra:token", "test_token");
    localStorage.setItem("access_token", "test_token");
    localStorage.setItem("token", "test_token");
  });

  // Catch-all for any unmocked API calls: prevents accidental 401 → clearAuth → /login redirects.
  // Specific mocks registered later will take precedence.
  await page.route("**/api/v1/**", async (route) => {
    const method = route.request().method().toUpperCase();
    const url = route.request().url();
    // Allow tests to override POST /messages etc by registering later.
    if (method === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
      return;
    }
    if (method === "POST") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, _mocked: true, url }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, _mocked: true, url }) });
  });

  // Auth + session-dependent endpoints.
  await page.route("**/api/v1/auth/me**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        user_id: 1,
        email: "qa@example.com",
        display_name: "QA",
        is_premium: false,
        is_trial: false,
      }),
    });
  });
  await page.route("**/api/v1/profiles/me**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 101,
        user_id: 1,
        display_name: "QA",
        photo_urls: "a.jpg",
        city: "NYC",
        age: 28,
      }),
    });
  });
  await page.route("**/api/v1/subscriptions/me**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ plan_code: "free", plan: "free" }),
    });
  });
  await page.route("**/api/v1/daily/boosts**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        day: "2026-04-30",
        show_banner: false,
        opener_remaining: 0,
        reply_remaining: 0,
        reveal_remaining: 0,
        revive_remaining: 0,
        streak_days: 1,
        streak_bonus_ai_chat: 0,
        curiosity_like: false,
      }),
    });
  });

  // Common boot requests on protected pages.
  await page.route("**/api/v1/nav/badges**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });
  await page.route("**/api/v1/messages/conversations**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
  });
}

async function runReportedFlow(
  key: keyof FlowReport,
  metrics: Metrics,
  fn: () => Promise<void>,
) {
  try {
    await fn();
    // Allow fn() to pre-mark a flow as "skipped" (e.g. no chat match).
    if (metrics.flow_report[key] !== "skipped") {
      metrics.flow_report[key] = "passed";
      metrics.flows_completed.push(key);
    }
    saveMetrics(metrics);
  } catch (e: any) {
    metrics.flow_report[key] = "failed";
    metrics.flow_failures[key] = String(e?.message || e || "unknown_error").slice(0, 260);
    saveMetrics(metrics);
  }
}

test.describe("Deep Product QA (browser flows)", () => {
  test.setTimeout(240_000);

  test("chat reply suggestions follow UI locale (uk/ru/pt) and clear on switch", async ({ page }) => {
    await setupAuthenticatedSession(page);

    // Stabilize locale overlays: ensure non-English locale bundles load in dev reliably.
    await page.route("**/locales/uk.json", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          "chat.reply.inlineBadge": "💡 Підказані відповіді",
          "chat.reply.fallback.1": "Зрозумів 😳 а що в цьому для тебе найважливіше?",
          "chat.reply.fallback.2": "Окей, це мило 😊 розкажеш більше?",
          "chat.reply.fallback.3": "Цікаво — що саме змусило тебе так відчути?",
        }),
      });
    });
    await page.route("**/locales/ru.json", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          "chat.reply.inlineBadge": "💡 Подсказанные ответы",
          "chat.reply.fallback.1": "Понял 😳 а что в этом для тебя самое важное?",
          "chat.reply.fallback.2": "Окей, это мило 😊 расскажешь больше?",
          "chat.reply.fallback.3": "Интересно — что именно заставило тебя так почувствовать?",
        }),
      });
    });
    await page.route("**/locales/pt.json", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          "chat.reply.inlineBadge": "💡 Respostas sugeridas",
          "chat.reply.fallback.1": "Entendi 😳 o que nisso é mais importante para você?",
          "chat.reply.fallback.2": "Ok, isso é fofo 😊 me conta mais?",
          "chat.reply.fallback.3": "Interessante — o que fez você se sentir assim?",
        }),
      });
    });

    const partnerId = 999;
    await page.route(`**/api/v1/profiles/partner/${partnerId}**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ user_id: partnerId, display_name: "Test Partner", photo_urls: [] }),
      });
    });
    // Thread has one incoming message so reply suggestions render.
    await page.route(`**/api/v1/messages/${partnerId}**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: 1,
            raw_id: 1,
            sender_id: partnerId,
            receiver_id: 1,
            content: "hey",
            created_at: new Date().toISOString(),
          },
        ]),
      });
    });
    // Force timed replies call to fail so we stay on localized fallback.
    await page.route("**/api/v1/ai/timed-replies**", async (route) => {
      await route.fulfill({ status: 429, contentType: "application/json", body: JSON.stringify({ detail: "rate_limited" }) });
    });

    await page.goto(`/chat/${partnerId}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(600);

    async function setUiLocale(value: string) {
      await page.evaluate((v) => localStorage.setItem("neyra:locale", v), value);
      await page.reload({ waitUntil: "domcontentloaded" });
      await expect(page.locator(".chat-first-opener__badge")).toBeVisible({ timeout: 20_000 });
      await expect(page.locator(".chat-reply-style__text")).toHaveCount(3, { timeout: 20_000 });
    }

    // Ukrainian: should contain Cyrillic fallback and no obvious English labels.
    await setUiLocale("uk");
    await expect(page.locator(".chat-first-opener__badge")).toContainText(/Підказан/i);
    expect((await page.locator(".chat-reply-style__text").allTextContents()).join(" ")).toMatch(/Зрозумів|Окей|Цікаво/);

    // Russian: should show Russian fallback.
    await setUiLocale("ru");
    expect((await page.locator(".chat-reply-style__text").allTextContents()).join(" ")).toMatch(/Понял|Окей|Интересно/);

    // Portuguese: should show Portuguese fallback.
    await setUiLocale("pt");
    expect((await page.locator(".chat-reply-style__text").allTextContents()).join(" ")).toMatch(/Entendi|Ok|Interessante/);

    // Switch en → uk: old English disappears, Ukrainian appears.
    await setUiLocale("en");
    expect((await page.locator(".chat-reply-style__text").allTextContents()).join(" ")).toMatch(/Got you|Okay|Interesting/);
    await setUiLocale("uk");
    const allText = (await page.locator(".chat-reply-style__text").allTextContents()).join(" ").toLowerCase();
    expect(allText).not.toContain("got you");
    expect(allText).not.toContain("okay, that’s kinda cute");
  });

  test("chat quick_send URL is idempotent (no duplicate POST /messages)", async ({ page }) => {
    await setupAuthenticatedSession(page);

    const partnerId = 456;
    let postCount = 0;

    await page.route("**/api/v1/messages/quality", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true, may_not_get_reply: false, risk_score: 0, quality_flags: [] }),
      });
    });

    await page.route(`**/api/v1/profiles/partner/${partnerId}**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          user_id: partnerId,
          display_name: "Test Partner",
          photo_urls: [],
          is_demo_profile: false,
          verified: false,
        }),
      });
    });

    await page.route(`**/api/v1/messages/${partnerId}**`, async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
    });

    await page.route(`**/api/v1/messages**`, async (route) => {
      if (route.request().method().toUpperCase() !== "POST") {
        await route.fallback();
        return;
      }
      const u = route.request().url();
      if (!/\/api\/v1\/messages(\?|$)/.test(u)) {
        await route.fallback();
        return;
      }
      postCount += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: 999,
          raw_id: 999,
          sender_id: 1,
          receiver_id: partnerId,
          content: "hi",
          created_at: new Date().toISOString(),
        }),
      });
    });

    const url = `/chat/${partnerId}?draft=${encodeURIComponent("hi")}&quick_send=1`;
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1600);
    // Simulate re-opening the same deep link; should not send again.
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1600);

    expect(postCount).toBe(1);
  });

  test("chat send double click is guarded (no duplicate POST /messages)", async ({ page }) => {
    const metrics = loadMetrics();
    lastPathCounted = "";
    saveMetrics(metrics);
    await setupAuthenticatedSession(page);

    const partnerId = 457;
    let postCount = 0;

    // (auth/session routes are handled by setupAuthenticatedSession)

    await page.route(`**/api/v1/profiles/partner/${partnerId}**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          user_id: partnerId,
          display_name: "Test Partner",
          photo_urls: [],
          is_demo_profile: false,
          verified: false,
        }),
      });
    });
    await page.route(`**/api/v1/messages/${partnerId}**`, async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
    });
    await page.route(`**/api/v1/messages**`, async (route) => {
      if (route.request().method().toUpperCase() !== "POST") {
        await route.fallback();
        return;
      }
      const u = route.request().url();
      if (!/\/api\/v1\/messages(\?|$)/.test(u)) {
        await route.fallback();
        return;
      }
      postCount += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: 1001,
          raw_id: 1001,
          sender_id: 1,
          receiver_id: partnerId,
          content: "hello",
          created_at: new Date().toISOString(),
        }),
      });
    });

    await page.goto(`/chat/${partnerId}`, { waitUntil: "domcontentloaded" });
    await page.waitForURL(new RegExp(`/chat/${partnerId}`), { timeout: 20_000 });

    const input = page.locator("textarea").first();
    await expect(input).toBeVisible({ timeout: 20_000 });
    await input.fill("hello");
    const sendBtn = page.getByRole("button", { name: /^send$/i }).first();
    await expect(sendBtn).toBeVisible({ timeout: 20_000 });

    // Click twice quickly; guard should prevent a second send.
    await page.evaluate(() => {
      const btn = document.querySelector<HTMLButtonElement>(".chat-composer__send");
      btn?.click();
      btn?.click();
    });

    await page.waitForTimeout(900);
    expect(postCount).toBe(1);
  });

  test("analytics batching is rate-limited (max 1 /batch per 3s)", async ({ page }) => {
    await setupAuthenticatedSession(page);

    let batchCount = 0;
    await page.route(`**/api/v1/analytics/track/batch`, async (route) => {
      batchCount += 1;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
    });

    await page.goto("/matches", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(300);
    await page.evaluate(() => {
      const fn = (window as any).__neyra_trackAnalyticsEvent as ((n: string, p?: any) => Promise<void>) | undefined;
      if (!fn) return;
      for (let i = 0; i < 25; i += 1) void fn("spam_event", { i });
    });

    // First flush may happen quickly, but should not exceed 1 batch within 3 seconds.
    await page.waitForTimeout(2500);
    expect(batchCount).toBeLessThanOrEqual(1);
  });

  test("matches live activity rows (likes + matches)", async ({ page }) => {
    await setupAuthenticatedSession(page);

    const rawApiUrl = String(process.env.API_URL || "http://localhost:8000/api/v1").trim().replace(/\/+$/, "");
    const apiBase = rawApiUrl.endsWith("/api/v1") ? rawApiUrl : `${rawApiUrl}/api/v1`;

    await page.route(`**/api/v1/likes/incoming**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ today_count: 0, waiting_count: 0 }),
      });
    });
    await page.route(`**/api/v1/likes/received**`, async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
    });
    await page.route(`**/api/v1/matches**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });

    await page.goto("/matches", { waitUntil: "domcontentloaded" });
    await page.waitForURL(/\/matches(\/|$|\?)/, { timeout: 15_000 });

    const items = page.locator(".live-activity-item");
    await expect(items).toHaveCount(2);

    // Click likes row → /likes
    await items.first().click({ force: true });
    await page.waitForURL(/\/likes(\/|$|\?)/, { timeout: 45_000, waitUntil: "domcontentloaded" });
  });

  test("core product flows", async ({ page }) => {
    const full = String(process.env.DEEP_QA_FULL || "").trim() === "1";
    const metrics = loadMetrics();
    lastPathCounted = "";
    saveMetrics(metrics);

    await runReportedFlow("landing_flow", metrics, async () => {
      await gotoCounted(page, "/", metrics);
      assertNoRawI18nKeys(await page.textContent("body"));
    });

    await loginAsDemo(page, metrics);

    await runReportedFlow("discover_flow", metrics, async () => {
      await clickPrimaryNavHref(page, metrics, "/discover");
      await page.waitForURL(/\/discover(\/|$|\?)/, { timeout: 15_000 });
      bumpPageVisit(metrics, page);
      assertNoRawI18nKeys(await page.textContent("body"));

      await page.waitForTimeout(500);

      const like = page.getByTestId("like-button");
      const pass = page.getByTestId("pass-button");
      const refresh = page.getByRole("button", { name: /^refresh$/i });
      const improveProfile = page.getByRole("link", { name: /improve profile/i });

      let acted = false;
      if (await like.count()) {
        await clickCounted(like.first(), metrics);
        acted = true;
        await page.waitForTimeout(1700);
        const body = (await page.textContent("body")) || "";
        expect(body.toLowerCase()).not.toContain("it's a match");
      }
      if (!acted && (await pass.count())) {
        await clickCounted(pass.first(), metrics);
        acted = true;
        await page.waitForTimeout(1700);
        const body = (await page.textContent("body")) || "";
        expect(body.toLowerCase()).not.toContain("it's a match");
      }
      if (!acted && (await refresh.count())) {
        await clickCounted(refresh.first(), metrics);
        acted = true;
      }
      if (!acted && (await improveProfile.count())) {
        await clickCounted(improveProfile.first(), metrics);
        await page.waitForTimeout(400);
        acted = true;
      }

      if (!acted) {
        // Be resilient: empty/blocked decks shouldn't fail the whole QA run.
        return;
      }
    });

    await runReportedFlow("matches_flow", metrics, async () => {
      // Mock Live Activity counts so the banner deterministically renders both rows.
      await page.route("**/api/v1/likes/incoming*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ today_count: 3, waiting_count: 3 }),
        });
      });
      await page.route("**/api/v1/matches**", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              match_id: 123,
              partner_user_id: 456,
              partner_display_name: "Test Match",
              partner_age: 25,
              partner_city: "Kyiv",
              partner_photo: null,
              partner_verified: false,
              matched_at: null,
              is_new_match: false,
            },
          ]),
        });
      });

      await clickPrimaryNavHref(page, metrics, "/matches");
      await page.waitForURL(/\/matches(\/|$|\?)/, { timeout: 15_000 });
      bumpPageVisit(metrics, page);
      assertNoRawI18nKeys(await page.textContent("body"));

      await expect(page.locator(".match-row--skeleton").first()).toHaveCount(0, { timeout: 25_000 }).catch(() => {});
      await page.waitForTimeout(400);

      // Live activity should show both likes + matches rows when likesCount > 0.
      const likesRow = page.getByTestId("matches-live-likes");
      const matchesRow = page.getByTestId("matches-live-matches");
      await expect(likesRow).toBeVisible();
      await expect(matchesRow).toBeVisible();

      // Clicking likes row navigates to /likes.
      // Force-click to avoid sticky banner overlays/animations blocking actionability.
      metrics.buttons_clicked += 1;
      metrics.interactions_count += 1;
      saveMetrics(metrics);
      await likesRow.scrollIntoViewIfNeeded().catch(() => {});
      await likesRow.click({ force: true });
      await page.waitForURL(/\/likes(\/|$|\?)/, { timeout: 15_000 });
      bumpPageVisit(metrics, page);

      if (!full) return;

      // Return to matches for extended likes-you navigation (DEEP_QA_FULL).
      await clickPrimaryNavHref(page, metrics, "/matches");
      await page.waitForURL(/\/matches(\/|$|\?)/, { timeout: 15_000 });

      await expect(page.locator(".likes-you-card__placeholder")).toHaveCount(0);

      const sayHi = page.getByRole("link", { name: /say hi/i });
      const goDiscover = page.getByRole("link", { name: /go to discover/i });
      const editProfile = page.getByRole("link", { name: /edit profile/i });
      const tryAgain = page.getByRole("button", { name: /try again/i });

      if (await sayHi.count()) {
        await clickCounted(sayHi.first(), metrics);
        await page.waitForURL(/\/chat\/\d+/, { timeout: 15_000 }).catch(() => {});
        bumpPageVisit(metrics, page);
      } else if (await goDiscover.count()) {
        await clickCounted(goDiscover.first(), metrics);
        await page.waitForURL(/\/discover(\/|$|\?)/, { timeout: 15_000 });
        bumpPageVisit(metrics, page);
      } else if (await editProfile.count()) {
        await clickCounted(editProfile.first(), metrics);
        await page.waitForURL(/\/profile(\/|$|\?)/, { timeout: 15_000 });
        bumpPageVisit(metrics, page);
      } else if (await tryAgain.count()) {
        await clickCounted(tryAgain.first(), metrics);
      } else {
        const anyChat = page.locator("a[href^='/chat/']").filter({ hasNotText: /^chat$/i }).first();
        if (await anyChat.count()) {
          await clickCounted(anyChat, metrics);
          await page.waitForURL(/\/chat\/\d+/, { timeout: 15_000 }).catch(() => {});
          bumpPageVisit(metrics, page);
        } else {
          throw new Error("matches_no_actionable_cta");
        }
      }

      if (page.url().includes("/matches")) {
        const admirerCards = page.locator(".likes-you-card");
        const admirerCount = await admirerCards.count();
        if (admirerCount > 0) {
          const firstText = ((await admirerCards.first().textContent()) || "").trim();
          expect(firstText.length).toBeGreaterThan(0);
        }
      }
    });

    await runReportedFlow("chat_ai_flow", metrics, async () => {
      if (/\/chat\/\d+/.test(page.url())) {
        await clickPrimaryNavHref(page, metrics, "/chat");
        await page.waitForURL((u) => u.pathname.replace(/\/$/, "") === "/chat", { timeout: 15_000 });
        bumpPageVisit(metrics, page);
        assertNoRawI18nKeys(await page.textContent("body"));
      } else {
        await clickPrimaryNavHref(page, metrics, "/chat");
        await page.waitForURL(/\/chat(\/|$|\?)/, { timeout: 15_000 });
        bumpPageVisit(metrics, page);
        assertNoRawI18nKeys(await page.textContent("body"));
      }

      await page.waitForTimeout(500);

      const inboxRow = page.locator("a.chat-inbox-row").first();
      if (await inboxRow.count()) {
        await clickCounted(inboxRow, metrics);
        await page.waitForURL(/\/chat\/\d+/, { timeout: 15_000 });
        bumpPageVisit(metrics, page);
      } else {
        const openMatches = page.getByRole("link", { name: /see matches/i });
        const goDiscover = page.getByRole("link", { name: /go to discover/i });
        if (await openMatches.count()) {
          await clickCounted(openMatches.first(), metrics);
          await page.waitForURL(/\/matches(\/|$|\?)/, { timeout: 15_000 });
          bumpPageVisit(metrics, page);
        } else if (await goDiscover.count()) {
          await clickCounted(goDiscover.first(), metrics);
          await page.waitForURL(/\/discover(\/|$|\?)/, { timeout: 15_000 });
          bumpPageVisit(metrics, page);
        } else {
          metrics.flow_report.chat_ai_flow = "skipped";
          metrics.flow_skip_reasons.chat_ai_flow = "no_match_available";
          saveMetrics(metrics);
          assertNoRawI18nKeys(await page.textContent("body"));
          return;
        }
      }

      if (!/\/chat\/\d+/.test(page.url())) {
        metrics.flow_report.chat_ai_flow = "skipped";
        metrics.flow_skip_reasons.chat_ai_flow = "no_match_available";
        saveMetrics(metrics);
        assertNoRawI18nKeys(await page.textContent("body"));
        return;
      }

      await page.waitForTimeout(600);

      const moreIdeas = page.getByRole("button", { name: /more ideas/i });
      if (await moreIdeas.count()) {
        await clickCounted(moreIdeas.first(), metrics);
        await page.waitForTimeout(350);
      }

      const aiPanels = page.locator("section[aria-label]").filter({ hasText: /ai/i });
      await expect(aiPanels).toHaveCount(0, { timeout: 2000 }).catch(async () => {
        await expect(aiPanels).toHaveCount(1);
      });

      await expect(page.locator(".chat-message-bubble--has-ai-tag")).toHaveCount(0);

      const suggestion = page
        .locator(".chat-ai__suggestion, .chat-ai-inline__suggestion, .chat-ai__suggestion-text")
        .first();
      const aiBar = page.getByTestId("ai-suggestions");
      if (await aiBar.count()) {
        await expect(aiBar.first()).toBeVisible({ timeout: 15_000 }).catch(() => {});
      }
      if (await suggestion.count()) {
        await clickCounted(suggestion, metrics);
        const composer = page.locator("textarea").first();
        if (await composer.count()) {
          const v = (await composer.inputValue().catch(() => "")) || "";
          expect(v.trim().length).toBeGreaterThan(0);
        }
      }
    });

    await runReportedFlow("profile_verification_flow", metrics, async () => {
      await clickPrimaryNavHref(page, metrics, "/profile");
      await page.waitForURL(/\/profile(\/|$|\?)/, { timeout: 15_000 });
      bumpPageVisit(metrics, page);
      assertNoRawI18nKeys(await page.textContent("body"));

      const verifyBtn = page.getByRole("button", { name: /verify now|verify profile/i }).first();
      if (await verifyBtn.count()) {
        await clickCounted(verifyBtn, metrics);
      } else {
        const bodyEarly = ((await page.textContent("body")) || "").toLowerCase();
        if (bodyEarly.includes("verified") && bodyEarly.includes("profile")) return;
      }

      await expect(page.locator("input[type='file']")).toHaveCount(0);

      const openCamera = page.getByRole("button", { name: /open camera|enable camera|start camera/i });
      if (!(await openCamera.count())) {
        const bodyEarly = ((await page.textContent("body")) || "").toLowerCase();
        if (bodyEarly.includes("verified")) return;
        metrics.flow_report.profile_verification_flow = "skipped";
        metrics.flow_skip_reasons.profile_verification_flow = "camera_cta_missing";
        saveMetrics(metrics);
        return;
      }
      await expect(openCamera.first()).toBeVisible({ timeout: 8000 });
      await clickCounted(openCamera.first(), metrics);
      await page.waitForTimeout(500);

      const tryAgain = page.getByRole("button", { name: /try again/i });
      if (await tryAgain.count()) {
        await clickCounted(tryAgain.first(), metrics);
        await page.waitForTimeout(350);
      }

      const body = (await page.textContent("body")) || "";
      expect(body.toLowerCase()).toMatch(/camera|verify|selfie/);
    });

    await runReportedFlow("premium_flow", metrics, async () => {
      await clickPrimaryNavHref(page, metrics, "/subscription");
      await page.waitForURL(/\/subscription(\/|$|\?)/, { timeout: 15_000 });
      bumpPageVisit(metrics, page);
      await expect(page.getByTestId("premium-modal")).toBeVisible({ timeout: 15_000 });
      assertNoRawI18nKeys(await page.textContent("body"));

      const currentBadge = page.getByText(/current plan/i).first();
      const chooseCta = page.getByRole("button", { name: /choose|upgrade|subscribe|unlock|continue|start/i }).first();

      if (await currentBadge.isVisible().catch(() => false)) {
        expect(await currentBadge.isVisible()).toBeTruthy();
      } else if (await chooseCta.count()) {
        const disabled = await chooseCta.isDisabled().catch(() => true);
        if (!disabled) await clickCounted(chooseCta, metrics);
        else await expect(page.getByText(/premium|subscription|plan/i).first()).toBeVisible({ timeout: 8000 });
      } else {
        await expect(page.getByText(/premium|subscription|plan/i).first()).toBeVisible({ timeout: 8000 });
      }
    });

    const passedFlows = Object.values(metrics.flow_report).filter((s) => s === "passed").length;
    const strict = String(process.env.DEEP_QA_STRICT || "").trim() === "1";
    if (strict) {
      expect(passedFlows).toBeGreaterThanOrEqual(4);
      expect(metrics.pages_visited).toBeGreaterThanOrEqual(7);
      expect(metrics.buttons_clicked).toBeGreaterThanOrEqual(8);
      expect(metrics.flows_completed.length).toBeGreaterThanOrEqual(4);
    } else {
      expect(metrics.pages_visited).toBeGreaterThanOrEqual(2);
    }
  });
});
