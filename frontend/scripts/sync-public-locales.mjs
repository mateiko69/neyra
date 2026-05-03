/**
 * Syncs translation JSON: master = locales/en.json.
 * - Ensures every locale.* key exists on en (native labels below).
 * - Writes public/locales/{code}.json and locales/{code}.json with identical keys as en.
 * - Preserves non-empty, sensible existing per-locale values from locales/{code}.json.
 * Usage: node scripts/sync-public-locales.mjs
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const LOCALES_SRC = path.join(ROOT, "locales");
const PUBLIC_OUT = path.join(ROOT, "public", "locales");

/** code -> native name (must match lib/i18n/locales.ts labels) */
const NATIVE_LOCALE_LABELS = {
  en: "English",
  uk: "Українська",
  ru: "Русский",
  es: "Español",
  pt: "Português",
  fr: "Français",
  de: "Deutsch",
  it: "Italiano",
  pl: "Polski",
  tr: "Türkçe",
  "zh-CN": "简体中文",
  "zh-TW": "繁體中文",
  ja: "日本語",
  ko: "한국어",
  hi: "हिन्दी",
  id: "Bahasa Indonesia",
  vi: "Tiếng Việt",
  th: "ไทย",
  ar: "العربية",
  he: "עברית",
  bg: "Български",
  nl: "Nederlands",
  sv: "Svenska",
  cs: "Čeština",
  ro: "Română",
  hu: "Magyar",
  el: "Ελληνικά",
  da: "Dansk",
  fi: "Suomi",
  no: "Norsk",
};

const CODES = Object.keys(NATIVE_LOCALE_LABELS);

function isRawPlaceholder(s) {
  const t = String(s ?? "").trim();
  if (!t) return true;
  if (/^locale\.[a-z]{2}(-[A-Z]{2})?$/i.test(t)) return true;
  if (t.startsWith("locale.") && t.length < 80) return true;
  if (/^[a-z][a-z0-9_]*\.[a-z][a-z0-9_.-]+$/i.test(t) && t.length < 96 && !t.includes(" ") && !t.includes(",")) {
    return true;
  }
  return false;
}

function readJson(p) {
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function ensureDir(d) {
  if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
}

ensureDir(PUBLIC_OUT);

const enPath = path.join(LOCALES_SRC, "en.json");
if (!fs.existsSync(enPath)) {
  console.error("Missing", enPath);
  process.exit(1);
}

/** @type {Record<string, string>} */
let masterEn = readJson(enPath);

for (const code of CODES) {
  const k = `locale.${code}`;
  const label = NATIVE_LOCALE_LABELS[code];
  if (!(k in masterEn) || isRawPlaceholder(masterEn[k])) {
    masterEn[k] = label;
  }
}

fs.writeFileSync(enPath, JSON.stringify(masterEn, null, 2) + "\n", "utf8");

const masterKeys = Object.keys(masterEn);
if (masterKeys.length === 0) {
  console.error("Empty en.json");
  process.exit(1);
}

for (const code of CODES) {
  /** @type {Record<string, string>} */
  let overlay = {};
  const overlayPath = path.join(LOCALES_SRC, `${code}.json`);
  if (fs.existsSync(overlayPath) && code !== "en") {
    try {
      overlay = readJson(overlayPath);
    } catch {
      overlay = {};
    }
  } else if (code === "zh-CN" && !fs.existsSync(overlayPath)) {
    // Migration helper: legacy "zh.json" (Simplified) → new "zh-CN.json".
    const legacy = path.join(LOCALES_SRC, "zh.json");
    if (fs.existsSync(legacy)) {
      try {
        overlay = readJson(legacy);
      } catch {
        overlay = {};
      }
    }
  }

  /** @type {Record<string, string>} */
  const out = {};
  for (const key of masterKeys) {
    const enVal = masterEn[key];
    if (code === "en") {
      out[key] = enVal;
      continue;
    }
    const cand = overlay[key];
    if (cand != null && String(cand).trim() !== "" && !isRawPlaceholder(cand)) {
      out[key] = cand;
    } else {
      out[key] = enVal;
    }
  }

  const json = JSON.stringify(out, null, 2) + "\n";
  fs.writeFileSync(path.join(PUBLIC_OUT, `${code}.json`), json, "utf8");
  fs.writeFileSync(path.join(LOCALES_SRC, `${code}.json`), json, "utf8");
}

console.log(`Synced ${CODES.length} locales, ${masterKeys.length} keys each → public/locales + locales/`);
