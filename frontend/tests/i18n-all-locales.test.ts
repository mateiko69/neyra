import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const ROOT = path.join(process.cwd());
const LOCALES_DIR = path.join(ROOT, "public", "locales");

const SUPPORTED = [
  "uk",
  "en",
  "ru",
  "es",
  "de",
  "fr",
  "pl",
  "ar",
  "tr",
  "it",
  "pt",
  "hi",
  "id",
  "ja",
  "ko",
  "nl",
  "sv",
  "no",
  "da",
  "fi",
  "cs",
  "ro",
  "hu",
  "el",
  "he",
  "th",
  "vi",
] as const;

function localeFile(code: string): string {
  if (code === "zh") return path.join(LOCALES_DIR, "zh-CN.json");
  return path.join(LOCALES_DIR, `${code}.json`);
}

test("all supported locale bundles exist", () => {
  for (const code of SUPPORTED) {
    assert.ok(fs.existsSync(localeFile(code)), `missing locale file for ${code}`);
  }
});

test("core nav and common keys do not leak raw i18n key tokens", () => {
  const rawKeyRe = /^(nav|common)\./i;
  const keys = [
    "navigation.discover",
    "navigation.matches",
    "navigation.chat",
    "navigation.profile",
    "navigation.premium",
    "nav.logout",
    "common.back",
    "common.save",
    "common.continue",
  ];
  for (const code of SUPPORTED) {
    const data = JSON.parse(fs.readFileSync(localeFile(code), "utf8")) as Record<string, string>;
    for (const k of keys) {
      const v = String(data[k] ?? "").trim();
      assert.ok(v.length > 0, `${code}: empty value for ${k}`);
      assert.ok(!rawKeyRe.test(v), `${code}: leaked raw key token for ${k}: ${v}`);
    }
  }
});

