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

async function runViewport(name, contextOpts, token, partnerUserId) {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext(contextOpts);
  const page = await context.newPage();
  await page.addInitScript((t) => {
    localStorage.setItem("neyra:token", t);
    localStorage.setItem("access_token", t);
    localStorage.setItem("token", t);
  }, token);

  const out = [];
  async function mark(key, fn) {
    try {
      await fn();
      out.push({ key, status: "PASS", details: "ok" });
    } catch (e) {
      out.push({ key, status: "FAIL", details: String(e?.message || e).slice(0, 140) });
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
    await page.goto(`${WEB_BASE}/discover`, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(1200);
    await assertNoBrokenText();
    const img = page.locator(".discover-card__img, .discover-mobile-mvp-card__photo, [data-testid='discover-card'] img").first();
    if (await img.count()) {
      const natural = await img.evaluate((el) => el.naturalWidth || 0);
      if (natural < 1) throw new Error("image naturalWidth=0");
    } else {
      throw new Error("discover image not found");
    }
  });

  await mark(`${name} /discover pass/ignore/like/undo/start-ai`, async () => {
    const pass = page.getByRole("button", { name: /pass|пропустити/i }).first();
    const ignore = page.getByRole("button", { name: /ignore|hide|ігнорувати/i }).first();
    const like = page.getByRole("button", { name: /like|подобається/i }).first();
    const undo = page.getByRole("button", { name: /undo|скасувати/i }).first();
    const ai = page.getByRole("button", { name: /start with ai|почати з ai/i }).first();
    if (!(await pass.count()) || !(await ignore.count()) || !(await like.count())) {
      throw new Error("required discover buttons missing");
    }
    await pass.click({ timeout: 10000 });
    await page.waitForTimeout(500);
    await ignore.click({ timeout: 10000 });
    await page.waitForTimeout(500);
    await like.click({ timeout: 10000 });
    await page.waitForTimeout(500);
    if (await undo.count()) {
      await undo.click({ timeout: 10000 });
    }
    if (await ai.count()) {
      await ai.click({ timeout: 10000 });
      await page.waitForTimeout(300);
    }
  });

  await mark(`${name} /matches avatars + actions`, async () => {
    await page.goto(`${WEB_BASE}/matches`, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(1200);
    await assertNoBrokenText();
    const avatar = page.locator(".match-row__avatar").first();
    if (!(await avatar.count())) throw new Error("match avatar missing");
    const natural = await avatar.evaluate((el) => el.naturalWidth || 0);
    if (natural < 1) throw new Error("avatar naturalWidth=0");
    const sayHi = page.getByRole("link", { name: /say hi|написати привіт/i }).first();
    if (!(await sayHi.count())) throw new Error("say hi missing");
    await sayHi.click({ timeout: 10000 });
    await page.waitForTimeout(500);
    await page.goto(`${WEB_BASE}/matches`, { waitUntil: "domcontentloaded", timeout: 60000 });
    const gen = page.getByRole("link", { name: /generate opener|generate phrase|згенерувати/i }).first();
    if (!(await gen.count())) throw new Error("generate phrase missing");
  });

  await mark(`${name} /chat scroll + composer`, async () => {
    await page.goto(`${WEB_BASE}/chat/${partnerUserId}`, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(1000);
    await assertNoBrokenText();
    const composer = page.locator("textarea").first();
    if (!(await composer.count())) throw new Error("composer missing");
    const canType = await composer.isEditable();
    if (!canType) throw new Error("composer not editable");
    if (name === "mobile") {
      const scrollOk = await page.evaluate(() => {
        const scroller = document.querySelector(".chat-thread-scroller, .chat-thread-body");
        if (!scroller) return false;
        const before = scroller.scrollTop;
        scroller.scrollTop = before + 120;
        return scroller.scrollTop !== before;
      });
      if (!scrollOk) throw new Error("mobile scroll not working");
    }
  });

  await mark(`${name} /profile upload mode`, async () => {
    await page.goto(`${WEB_BASE}/profile`, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(1200);
    await assertNoBrokenText();
    const disabledMsg = page.getByText(/Photo upload is temporarily disabled|Завантаження фото тимчасово вимкнене/i).first();
    if (await disabledMsg.count()) return;
    const editBtn = page.getByRole("button", { name: /edit|редагувати/i }).first();
    if (!(await editBtn.count())) throw new Error("profile edit button missing");
  });

  await mark(`${name} /premium loads`, async () => {
    await page.goto(`${WEB_BASE}/premium`, { waitUntil: "domcontentloaded", timeout: 60000 });
    await assertNoBrokenText();
  });

  await context.close();
  await browser.close();
  return out;
}

async function main() {
  const qaA = await registerAndPrepare("QaAlex", "man", "women");
  const qaB = await registerAndPrepare("QaBella", "woman", "men");

  const likeA = await api("POST", "/swipes", qaA.token, { target_user_id: qaB.userId, liked: true });
  if (!likeA.ok) throw new Error(`seed like A->B failed: ${likeA.status}`);
  const incoming = await api("GET", "/likes/incoming?limit=5", qaB.token);
  const admirerId = Number(incoming.json?.items?.[0]?.user_id ?? 0);
  if (incoming.ok && admirerId > 0) {
    const respond = await api("POST", "/likes/respond", qaB.token, { user_id: admirerId, action: "like" });
    if (!respond.ok) {
      // eslint-disable-next-line no-console
      console.warn(`seed respond like failed: ${respond.status} ${respond.text}`);
    }
  } else {
    // eslint-disable-next-line no-console
    console.warn(`seed incoming likes unavailable: ${incoming.status} ${incoming.text}`);
  }

  const desktop = await runViewport("desktop", { viewport: { width: 1440, height: 900 } }, qaB.token, qaA.userId);
  const mobile = await runViewport("mobile", { ...devices["iPhone 12"] }, qaB.token, qaA.userId);
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

