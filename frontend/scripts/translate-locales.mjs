/**
 * Applies deterministic core UI translations for non-English locales.
 *
 * Placeholder detection: for locale !== en, any key where `value === en.json[key]`
 * is treated as an untranslated English copy (loanwords like "Chat" / "Premium" count too).
 *
 * Rules:
 * - Only replaces when current value strictly equals English (preserves polished uk/ru).
 * - Writes frontend/locales/{code}.json and frontend/public/locales/{code}.json.
 *
 * For warmer, shorter native copy (onboarding, chat, buttons), run after syncing keys:
 *   npm run apply-native-tone
 *
 * Usage:
 *   node scripts/translate-locales.mjs
 *   node scripts/translate-locales.mjs --dry-run
 *   node scripts/translate-locales.mjs --report   # count EN-identical values per locale
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const LOCALES_DIR = path.join(ROOT, "locales");
const PUBLIC_DIR = path.join(ROOT, "public", "locales");
const DATA_FILE = path.join(__dirname, "core-ui-translations.json");

const DRY = process.argv.includes("--dry-run");
const REPORT = process.argv.includes("--report");

/** Keys that should use the same translated string as another key (en master must define both). */
const DERIVED_SAME_AS = {
  "people.actions.openChat": "matches.openChat",
  "people.trust.verified": "profile.verified",
};

function readJson(p) {
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

/** @type {Record<string, Record<string, string>>} */
const translations = readJson(DATA_FILE);
const en = readJson(path.join(LOCALES_DIR, "en.json"));

if (REPORT) {
  const codes = Object.keys(translations).filter((c) => c !== "en").sort();
  for (const locale of codes) {
    const filePath = path.join(LOCALES_DIR, `${locale}.json`);
    if (!fs.existsSync(filePath)) continue;
    const data = readJson(filePath);
    let placeholders = 0;
    const examples = [];
    for (const [key, v] of Object.entries(data)) {
      if (key in en && v === en[key]) {
        placeholders++;
        if (examples.length < 8) examples.push(key);
      }
    }
    console.log(`${locale}\tplaceholders=${placeholders}\texample_keys=${examples.join(",")}`);
  }
  process.exit(0);
}

const stats = { files: 0, keysPatched: 0, derivedPatched: 0 };

for (const [locale, row] of Object.entries(translations)) {
  if (locale === "en") continue;
  const filePath = path.join(LOCALES_DIR, `${locale}.json`);
  if (!fs.existsSync(filePath)) {
    console.warn("skip missing", filePath);
    continue;
  }
  /** @type {Record<string, string>} */
  const data = readJson(filePath);
  let patched = 0;

  for (const [key, value] of Object.entries(row)) {
    if (!(key in en)) continue;
    const enVal = en[key];
    if (data[key] === enVal && value != null && String(value).trim() !== "") {
      data[key] = value;
      patched++;
    }
  }

  for (const [targetKey, sourceKey] of Object.entries(DERIVED_SAME_AS)) {
    if (!(targetKey in en) || !(sourceKey in en)) continue;
    if (data[targetKey] !== en[targetKey]) continue;
    const fromRow = row[sourceKey];
    if (fromRow != null && String(fromRow).trim() !== "") {
      data[targetKey] = fromRow;
      stats.derivedPatched++;
      patched++;
    }
  }

  stats.files++;
  stats.keysPatched += patched;
  if (!DRY) {
    const out = JSON.stringify(data, null, 2) + "\n";
    fs.writeFileSync(filePath, out, "utf8");
    fs.writeFileSync(path.join(PUBLIC_DIR, `${locale}.json`), out, "utf8");
  }
}

console.log(DRY ? "[dry-run] would patch:" : "Patched:", stats);
