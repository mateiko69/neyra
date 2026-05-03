/**
 * Applies curated native-tone strings from native-tone-packs.mjs.
 * Overwrites existing values (authoritative QA pass for onboarding, chat, buttons, toasts).
 *
 * Usage: npm run apply-native-tone
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import packs, { onboardingDeep } from "./native-tone-packs.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const LOCALES_DIR = path.join(ROOT, "locales");
const PUBLIC_DIR = path.join(ROOT, "public", "locales");

const en = JSON.parse(fs.readFileSync(path.join(LOCALES_DIR, "en.json"), "utf8"));

let locales = 0;
let keyTouches = 0;

for (const [locale, basePatch] of Object.entries(packs)) {
  if (locale === "en" || !basePatch || typeof basePatch !== "object") continue;
  const deep = onboardingDeep[locale] || {};
  const patch = { ...deep, ...basePatch };
  locales += 1;
  for (const dir of [LOCALES_DIR, PUBLIC_DIR]) {
    const fp = path.join(dir, `${locale}.json`);
    if (!fs.existsSync(fp)) continue;
    const data = JSON.parse(fs.readFileSync(fp, "utf8"));
    for (const [k, v] of Object.entries(patch)) {
      if (!(k in en)) continue;
      if (v == null || String(v).trim() === "") continue;
      data[k] = v;
      if (dir === LOCALES_DIR) keyTouches += 1;
    }
    fs.writeFileSync(fp, JSON.stringify(data, null, 2) + "\n", "utf8");
  }
}

console.log(`apply-native-tone: ${locales} locale(s), ${keyTouches} key updates (locales/ mirror).`);
