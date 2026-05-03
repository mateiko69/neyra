/**
 * Locale bundle parity + sanity (Node built-in test runner).
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const PUBLIC = path.join(ROOT, "public", "locales");
const LOCALES_TS = path.join(ROOT, "lib", "i18n", "locales.ts");

test("every supported code from locales.ts has a public JSON file", () => {
  const src = fs.readFileSync(LOCALES_TS, "utf8");
  const codes = [...src.matchAll(/\{\s*code:\s*"([^"]+)"/g)].map((m) => m[1]);
  assert.ok(codes.includes("en"));
  assert.ok(codes.includes("zh-CN"));
  assert.ok(codes.includes("zh-TW"));
  for (const code of codes) {
    const fp = path.join(PUBLIC, `${code}.json`);
    assert.ok(fs.existsSync(fp), `missing ${code}.json`);
  }
});

test("every public locale JSON has same keys as en.json and no empty values", () => {
  const enPath = path.join(PUBLIC, "en.json");
  const en = JSON.parse(fs.readFileSync(enPath, "utf8"));
  const enKeys = Object.keys(en).sort();
  assert.ok(enKeys.length > 0);
  const files = fs.readdirSync(PUBLIC).filter((f) => f.endsWith(".json"));
  for (const f of files) {
    const p = path.join(PUBLIC, f);
    const data = JSON.parse(fs.readFileSync(p, "utf8"));
    const keys = Object.keys(data).sort();
    assert.deepEqual(keys, enKeys, f);
    for (const [k, v] of Object.entries(data)) {
      assert.ok(typeof v === "string" && v.trim().length > 0, `empty ${f} ${k}`);
    }
  }
});

test("dropdown labels: LOCALES native labels are never locale.* tokens", () => {
  const src = fs.readFileSync(LOCALES_TS, "utf8");
  const rows = [...src.matchAll(/label:\s*"([^"]*)"/g)].map((m) => m[1]);
  for (const label of rows) {
    assert.ok(!/^locale\.[a-z0-9.-]+$/i.test(label.trim()), label);
  }
});

test("RTL: ar and he marked rtl true in locales.ts", () => {
  const src = fs.readFileSync(LOCALES_TS, "utf8");
  assert.match(src, /\{\s*code:\s*"ar"[\s\S]*?rtl:\s*true/);
  assert.match(src, /\{\s*code:\s*"he"[\s\S]*?rtl:\s*true/);
});

test("I18nProvider exposes data-testid and data-dir for RTL QA", () => {
  const p = path.join(ROOT, "app", "components", "i18n", "I18nProvider.tsx");
  const src = fs.readFileSync(p, "utf8");
  assert.match(src, /data-testid="neyra-i18n-root"/);
  assert.match(src, /data-dir=\{dir\}/);
});

test("core UI strings differ from English for every non-en locale", () => {
  const transPath = path.join(ROOT, "scripts", "core-ui-translations.json");
  const trans = JSON.parse(fs.readFileSync(transPath, "utf8"));
  const coreKeys = [...Object.keys(trans.uk), "people.actions.openChat", "people.trust.verified"];
  const enPath = path.join(PUBLIC, "en.json");
  const en = JSON.parse(fs.readFileSync(enPath, "utf8"));
  const files = fs.readdirSync(PUBLIC).filter((f) => f.endsWith(".json"));
  for (const f of files) {
    const code = f.replace(/\.json$/, "");
    if (code === "en") continue;
    const data = JSON.parse(fs.readFileSync(path.join(PUBLIC, f), "utf8"));
    for (const k of coreKeys) {
      if (!(k in en)) continue;
      assert.notEqual(
        data[k],
        en[k],
        `${code}: ${k} must not equal English placeholder`,
      );
    }
  }
});

test("onboarding intro changes on uk/es locale switch and active locales are localized", () => {
  const en = JSON.parse(fs.readFileSync(path.join(PUBLIC, "en.json"), "utf8"));
  const uk = JSON.parse(fs.readFileSync(path.join(PUBLIC, "uk.json"), "utf8"));
  const es = JSON.parse(fs.readFileSync(path.join(PUBLIC, "es.json"), "utf8"));
  const introKeys = [
    "onboarding.intro.title",
    "onboarding.intro.subtitle",
    "onboarding.intro.ai_title",
    "onboarding.intro.smart_title",
    "onboarding.intro.real_title",
  ];
  for (const k of introKeys) {
    assert.ok(String(uk[k] || "").trim(), `uk missing ${k}`);
    assert.ok(String(es[k] || "").trim(), `es missing ${k}`);
    assert.notEqual(uk[k], en[k], `uk ${k} must change from English`);
    assert.notEqual(es[k], en[k], `es ${k} must change from English`);
    assert.notEqual(uk[k], es[k], `uk/es ${k} must differ when switching locale`);
  }

  for (const code of ["uk", "es", "ru", "de", "fr", "pl", "pt", "hi", "zh-CN", "zh-TW", "ar"]) {
    const data = JSON.parse(fs.readFileSync(path.join(PUBLIC, `${code}.json`), "utf8"));
    for (const k of introKeys) {
      assert.notEqual(data[k], en[k], `${code} ${k} must not be an English reset`);
    }
  }
});

test("founder, demo, and premium.support keys exist with non-empty EN values", () => {
  const enPath = path.join(PUBLIC, "en.json");
  const en = JSON.parse(fs.readFileSync(enPath, "utf8"));
  const required = [
    "founder.title",
    "founder.subtitle",
    "founder.body",
    "founder.continue",
    "founder.feedback",
    "founder.invite",
    "founder.support",
    "founder.skipLink",
    "founder.shareTitle",
    "founder.feedbackMailSubject",
    "founder.error",
    "demo.mode.title",
    "demo.mode.subtitle",
    "demo.badge",
    "demo.notice",
    "demo.profile.label",
    "demo.profile.disclaimer",
    "demo.chat.label",
    "demo.chat.disclaimer",
    "demo.chat.aiSimulation",
    "demo.chat.messageLabel",
    "demo.messages.opener.light",
    "demo.messages.opener.flirty",
    "demo.messages.opener.curious",
    "demo.messages.reply.light",
    "demo.messages.reply.flirty",
    "demo.messages.reply.curious",
    "demo.messages.revive.light",
    "demo.messages.revive.flirty",
    "demo.messages.revive.curious",
    "demo.messages.fallback",
    "demo.live.title",
    "demo.live.subtitle",
    "demo.live.enabled",
    "demo.live.disabled",
    "demo.live.status",
    "demo.live.replySpeed",
    "demo.live.ignoreRate",
    "demo.live.personalities",
    "demo.live.regeneratePersonalities",
    "demo.live.clearChats",
    "demo.live.enable",
    "demo.live.disable",
    "demo.cta.inviteFriends",
    "demo.cta.tryAiSuggestions",
    "premium.support.title",
    "premium.support.body",
    "premium.support.cta",
    "premium.support.bannerTitle",
    "premium.support.bannerBody",
    "premium.support.point1",
  ];
  for (const k of required) {
    assert.ok(k in en, `missing ${k}`);
    assert.ok(typeof en[k] === "string" && String(en[k]).trim().length > 0, `empty en ${k}`);
  }
});

test("public bundles: founder, demo, and premium.support values are never raw i18n keys", () => {
  const prefixRe = /^(founder\.|demo\.|premium\.support\.)/;
  const files = fs.readdirSync(PUBLIC).filter((f) => f.endsWith(".json"));
  for (const f of files) {
    const data = JSON.parse(fs.readFileSync(path.join(PUBLIC, f), "utf8"));
    for (const [k, v] of Object.entries(data)) {
      if (!prefixRe.test(k)) continue;
      const s = String(v).trim();
      assert.notEqual(s, k, `${f}: value must not equal key ${k}`);
    }
  }
});

test("no locale.* as a translation value in public bundles", () => {
  const files = fs.readdirSync(PUBLIC).filter((f) => f.endsWith(".json"));
  for (const f of files) {
    const data = JSON.parse(fs.readFileSync(path.join(PUBLIC, f), "utf8"));
    for (const [k, v] of Object.entries(data)) {
      const s = String(v).trim();
      if (/^locale\.[a-z]{2}(-[A-Z]{2})?$/i.test(s)) {
        assert.fail(`${f} ${k}: raw locale token ${s}`);
      }
    }
  }
});

test("errors.api keys for API message translation exist in en.json", () => {
  const enPath = path.join(PUBLIC, "en.json");
  const en = JSON.parse(fs.readFileSync(enPath, "utf8"));
  const required = [
    "errors.api.generic",
    "errors.api.userBlocked",
    "errors.api.matchRequired",
    "errors.api.rateLimited",
    "errors.api.rateLimitedDetail",
    "errors.api.unreachable",
    "errors.api.requestFailedStatus",
    "errors.api.messageBlocked",
    "errors.api.moderationBlocked",
    "errors.api.policy",
    "errors.api.auth.emailTaken",
    "errors.api.auth.invalidCredentials",
    "errors.api.upload.empty",
    "errors.api.upload.itemFailed",
    "errors.api.chat.messageBlocked",
    "errors.api.subscription.invalidPlan",
  ];
  for (const k of required) {
    assert.ok(k in en, `missing ${k}`);
    assert.ok(typeof en[k] === "string" && String(en[k]).trim().length > 0, `empty en ${k}`);
  }
});

test("every locale has all referrals.reward.* keys from en with non-empty values", () => {
  const enPath = path.join(PUBLIC, "en.json");
  const en = JSON.parse(fs.readFileSync(enPath, "utf8"));
  const rewardKeys = Object.keys(en).filter((k) => k.startsWith("referrals.reward."));
  assert.ok(rewardKeys.length >= 8, "expected referrals.reward.* keys in en.json");
  const files = fs.readdirSync(PUBLIC).filter((f) => f.endsWith(".json"));
  for (const f of files) {
    const data = JSON.parse(fs.readFileSync(path.join(PUBLIC, f), "utf8"));
    for (const k of rewardKeys) {
      assert.ok(k in data, `${f} missing ${k}`);
      assert.ok(typeof data[k] === "string" && data[k].trim().length > 0, `${f} empty ${k}`);
    }
  }
});

test("demo.messages.* and demo.live.* exist in en + uk and uk is not English copy", () => {
  const en = JSON.parse(fs.readFileSync(path.join(PUBLIC, "en.json"), "utf8"));
  const uk = JSON.parse(fs.readFileSync(path.join(PUBLIC, "uk.json"), "utf8"));
  const keys = Object.keys(en).filter((k) => k.startsWith("demo.messages.") || k.startsWith("demo.live."));
  assert.ok(keys.length >= 18, "expected demo.messages.* and demo.live.* keys");
  for (const k of keys) {
    assert.ok(k in uk && String(uk[k]).trim(), `uk missing or empty ${k}`);
    assert.notEqual(String(uk[k]).trim(), String(en[k]).trim(), `${k}: uk should not equal en`);
  }
});

test("localization audit keys exist in en + uk public bundles", () => {
  const en = JSON.parse(fs.readFileSync(path.join(PUBLIC, "en.json"), "utf8"));
  const uk = JSON.parse(fs.readFileSync(path.join(PUBLIC, "uk.json"), "utf8"));
  const keys = [
    "admin.errors.generic",
    "chat.thread.errors.voiceBusy",
    "common.inviteLinkManual",
    "people.errors.loadPartner",
    "people.errors.safetyAction",
    "profile.aiMemory.cleared",
    "profile.errors.saveFailed",
    "profile.errors.deleteFailed",
    "profile.verify.liveness.hintCenter",
    "profile.verify.errors.cameraRequiresHttps",
  ];
  for (const k of keys) {
    assert.ok(k in en && String(en[k]).trim(), `en missing ${k}`);
    assert.ok(k in uk && String(uk[k]).trim(), `uk missing ${k}`);
  }
});

test("audited pages wire apiFailureToI18nText or translateApiUserMessage (no raw error.message toasts)", () => {
  const rels = [
    "app/onboarding/page.tsx",
    "app/profile/page.tsx",
    "app/discover/page.tsx",
    "app/founder-welcome/page.tsx",
    "app/people/[userId]/page.tsx",
    "app/components/PhotoUploader.tsx",
    "lib/chat/useChatInboxController.ts",
  ];
  const bad = /rawI18nText\(\s*error(?:Value)?\.message/;
  for (const rel of rels) {
    const fp = path.join(ROOT, rel);
    const src = fs.readFileSync(fp, "utf8");
    assert.doesNotMatch(src, bad, `${rel} should not pass error.message directly to rawI18nText`);
  }
});
