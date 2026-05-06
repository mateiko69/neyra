import { chromium, devices, request as playwrightRequest } from "playwright";

const WEB_BASE = process.env.QA_WEB_BASE || "https://www.getneyra.app";
const API_BASE = (process.env.QA_API_BASE || "https://api.getneyra.app/api/v1/").replace(/\/?$/, "/");

function tempCred(prefix) {
  const stamp = `${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
  return {
    email: `${prefix}_${stamp}@example.com`,
    password: `Qa_${stamp}_Aa1!`,
  };
}

async function api(method, path, token, body) {
  const ctx = await playwrightRequest.newContext({ baseURL: API_BASE });
  const relPath = String(path || "").replace(/^\/+/, "");
  const headers = { "content-type": "application/json" };
  if (token) headers.authorization = `Bearer ${token}`;
  const upper = String(method || "GET").toUpperCase();
  const resp =
    upper === "GET"
      ? await ctx.get(relPath, { headers })
      : upper === "PUT"
        ? await ctx.put(relPath, { headers, data: body ?? {} })
        : upper === "PATCH"
          ? await ctx.patch(relPath, { headers, data: body ?? {} })
          : await ctx.post(relPath, { headers, data: body ?? {} });
  const text = await resp.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = null;
  }
  await ctx.dispose();
  return { ok: resp.ok(), status: resp.status(), json, text };
}

function feedCardsLen(body) {
  if (Array.isArray(body)) return body.length;
  if (body && typeof body === "object") {
    if (Array.isArray(body.feed)) return body.feed.length;
    if (Array.isArray(body.cards)) return body.cards.length;
  }
  return 0;
}

async function registerAndPrepare(displayName, gender, interestedIn) {
  const creds = tempCred(displayName.toLowerCase());
  const reg = await api("POST", "/auth/register", null, {
    email: creds.email,
    password: creds.password,
    display_name: displayName,
  });
  if (!reg.ok || !reg.json?.access_token) {
    throw new Error(`register failed for ${displayName}: ${reg.status} ${reg.text}`);
  }
  const token = String(reg.json.access_token);
  const me = await api("GET", "/auth/me", token);
  const userId = Number(me.json?.id ?? me.json?.user_id ?? 0);
  if (!me.ok || userId < 1) throw new Error(`auth/me failed for ${displayName}: ${me.status} ${me.text}`);

  const profilePatch = await api("PATCH", "/profiles/me", token, {
    display_name: displayName,
    bio: `${displayName} QA profile`,
    date_of_birth: "1997-02-03",
    city: "Kyiv",
    gender,
    interested_in: interestedIn,
    preferred_gender: "everyone",
    relationship_goal: "dating",
    vibe: "warm",
    interests: "music,coffee,travel",
    lifestyle_tags: "active,kind",
    photo_urls: `https://picsum.photos/seed/${encodeURIComponent(displayName)}/640/960`,
    native_language: "en",
    min_preferred_age: 18,
    max_preferred_age: 80,
    onboarding_completed: true,
  });
  if (![200, 201].includes(profilePatch.status) && !profilePatch.ok) {
    throw new Error(`profile setup failed for ${displayName}: ${profilePatch.status}`);
  }
  return { token, userId, displayName, ...creds };
}

async function injectToken(page, token) {
  await page.evaluate((t) => {
    try {
      localStorage.setItem("neyra:token", t);
      localStorage.setItem("access_token", t);
      localStorage.setItem("token", t);
    } catch {
      /* ignore */
    }
  }, token);
}

async function runViewport(name, contextOpts, { discoverToken, sessionToken, chatPartnerUserId }) {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext(contextOpts);
  const page = await context.newPage();

  const out = [];
  async function mark(key, fn) {
    try {
      await fn();
      out.push({ key, status: "PASS", details: "ok" });
    } catch (e) {
      out.push({ key, status: "FAIL", details: String(e?.message || e).slice(0, 180) });
    }
  }

  const badTokens = [/discover\.reason\./i, /strong_profile_quality/i, /вЂ/i, /вњ/i, /рџ/i];
  async function assertNoBrokenText() {
    const body = (await page.textContent("body")) || "";
    for (const re of badTokens) {
      if (re.test(body)) throw new Error(`broken_text:${re}`);
    }
  }

  await mark(`${name} /discover photo visible`, async () => {
    await injectToken(page, discoverToken);
    await page.goto(`${WEB_BASE}/discover`, { waitUntil: "domcontentloaded", timeout: 60_000 });
    const pic = page.getByTestId("discover-photo");
    await pic.first().waitFor({ state: "visible", timeout: 25_000 });
    await assertNoBrokenText();
    const nw = await pic.first().evaluate((el) => (el instanceof HTMLImageElement ? el.naturalWidth || 0 : 0));
    if (nw < 1) throw new Error(`discover-photo naturalWidth=${nw}`);
  });

  await mark(`${name} /discover pass/ignore/like/undo/start-ai`, async () => {
    await injectToken(page, discoverToken);
    await page.goto(`${WEB_BASE}/discover`, { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.getByTestId("discover-photo").first().waitFor({ state: "visible", timeout: 25_000 }).catch(() => {});
    const pass = page.getByRole("button", { name: /pass|пропустити/i }).first();
    const ignore = page.getByRole("button", { name: /ignore|hide|ігнорувати/i }).first();
    const like = page.getByRole("button", { name: /like|подобається/i }).first();
    if (!(await pass.count()) || !(await ignore.count()) || !(await like.count())) {
      throw new Error("required discover buttons missing");
    }
    await pass.click({ timeout: 12_000 });
    await page.waitForTimeout(400);
    await ignore.click({ timeout: 12_000 });
    await page.waitForTimeout(400);
    await like.click({ timeout: 12_000 });
    await page.waitForTimeout(400);
    const undo = page.getByRole("button", { name: /undo|скасувати/i }).first();
    if (await undo.count()) await undo.click({ timeout: 12_000 });
    const ai = page.getByRole("button", { name: /start with ai|почати з ai/i }).first();
    if (await ai.count()) await ai.click({ timeout: 5000 }).catch(() => {});
  });

  await mark(`${name} /matches avatars + actions`, async () => {
    await injectToken(page, sessionToken);
    await page.goto(`${WEB_BASE}/matches`, { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page
      .waitForResponse((r) => /\/api\/v1\/matches(?:\?|$)/.test(r.url()) && r.ok(), { timeout: 25_000 })
      .catch(() => {});
    await page.waitForTimeout(400);
    await assertNoBrokenText();
    const avatar = page.getByTestId("match-avatar-img").first();
    await avatar.waitFor({ state: "visible", timeout: 20_000 });
    const nw = await avatar.evaluate((el) => (el instanceof HTMLImageElement ? el.naturalWidth || 0 : 0));
    if (nw < 1) throw new Error(`match avatar naturalWidth=${nw}`);
    const sayHi = page.getByRole("link", { name: /say hi|написати привіт/i }).first();
    if (!(await sayHi.count())) throw new Error("say hi missing");
    await sayHi.click({ timeout: 12_000 });
    await page.waitForTimeout(500);
    await page.goto(`${WEB_BASE}/matches`, { waitUntil: "domcontentloaded", timeout: 60_000 });
    const gen = page.getByRole("link", { name: /generate opener|generate phrase|згенерувати/i }).first();
    if (!(await gen.count())) throw new Error("generate phrase missing");
  });

  await mark(`${name} /chat scroll + composer`, async () => {
    await injectToken(page, sessionToken);
    await page.goto(`${WEB_BASE}/chat/${chatPartnerUserId}`, { waitUntil: "domcontentloaded", timeout: 60_000 });
    await assertNoBrokenText();
    const composer = page.getByTestId("chat-composer-input");
    await composer.waitFor({ state: "visible", timeout: 25_000 });
    await page.waitForFunction(
      () => {
        const el = document.querySelector('[data-testid="chat-composer-input"]');
        return el instanceof HTMLTextAreaElement && !el.disabled;
      },
      null,
      { timeout: 25_000 },
    );
    if (!(await composer.isEditable())) throw new Error("composer not editable");
    const send = page.getByTestId("chat-send-button");
    if (!(await send.count())) throw new Error("chat send missing");
    if (name === "mobile") {
      const scroller = page.locator('[data-testid="chat-messages"] .chat-thread-scroller');
      await scroller.waitFor({ state: "attached", timeout: 15_000 });
      const scrollOk = await scroller.evaluate((el) => {
        if (!(el instanceof HTMLElement)) return false;
        const max = Math.max(0, el.scrollHeight - el.clientHeight);
        const before = el.scrollTop;
        el.scrollTop = Math.min(max, before + 200);
        return el.scrollTop !== before || max <= 4;
      });
      if (!scrollOk) throw new Error("mobile scroll did not advance");
    }
  });

  await mark(`${name} /profile upload mode`, async () => {
    await injectToken(page, sessionToken);
    await page.goto(`${WEB_BASE}/profile`, { waitUntil: "domcontentloaded", timeout: 60_000 });
    await assertNoBrokenText();
    const disabledMsg = page.getByText(/Photo upload is temporarily disabled|Завантаження фото тимчасово вимкнене/i).first();
    const photoEdit = page.getByTestId("profile-photo-edit");
    for (let i = 0; i < 60; i++) {
      if ((await disabledMsg.count()) > 0 || (await photoEdit.count()) > 0) break;
      await page.waitForTimeout(100);
    }
    if (await disabledMsg.count()) return;
    if (!(await photoEdit.count())) throw new Error("profile photo edit control missing");
    await photoEdit.first().waitFor({ state: "visible", timeout: 12_000 });
  });

  await mark(`${name} /premium loads`, async () => {
    await injectToken(page, sessionToken);
    await page.goto(`${WEB_BASE}/premium`, { waitUntil: "domcontentloaded", timeout: 60_000 });
    await assertNoBrokenText();
  });

  await context.close();
  await browser.close();
  return out;
}

async function main() {
  const qaA = await registerAndPrepare("QaAlex", "man", "women");
  const qaB = await registerAndPrepare("QaBella", "woman", "men");

  const likeForward = await api("POST", "/swipes", qaA.token, { target_user_id: qaB.userId, liked: true });
  if (!likeForward.ok) throw new Error(`seed like A->B failed: ${likeForward.status} ${likeForward.text}`);

  const likeBack = await api("POST", "/swipes", qaB.token, { target_user_id: qaA.userId, liked: true });
  const backJson = likeBack.json && typeof likeBack.json === "object" ? likeBack.json : {};
  if (!likeBack.ok || !backJson.matched) {
    throw new Error(`mutual match expected after B liked A: http=${likeBack.status} matched=${backJson?.matched} body=${likeBack.text}`);
  }

  const feedA = await api("GET", "/discover/feed?limit=12", qaA.token);
  const feedB = await api("GET", "/discover/feed?limit=12", qaB.token);
  const lenA = feedCardsLen(feedA.json);
  const lenB = feedCardsLen(feedB.json);
  const discoverToken = lenA >= lenB ? qaA.token : qaB.token;

  const desktop = await runViewport("desktop", { viewport: { width: 1440, height: 900 } }, {
    discoverToken,
    sessionToken: qaB.token,
    chatPartnerUserId: qaA.userId,
  });
  const mobile = await runViewport("mobile", { ...devices["iPhone 12"] }, {
    discoverToken,
    sessionToken: qaB.token,
    chatPartnerUserId: qaA.userId,
  });
  const all = [...desktop, ...mobile];

  console.log("QA_RESULT_START");
  for (const row of all) console.log(`${row.key} | ${row.status} | ${row.details}`);
  console.log("QA_RESULT_END");

  const failed = all.filter((r) => r.status === "FAIL");
  if (failed.length) {
    process.exitCode = 1;
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
