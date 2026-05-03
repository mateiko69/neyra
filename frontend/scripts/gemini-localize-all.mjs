/**
 * Full locale generator for NEYRA using Gemini.
 *
 * It translates every non-English locale value that is still identical to en.json,
 * preserves already polished human translations, keeps ICU placeholders unchanged,
 * writes both frontend/locales and frontend/public/locales, and emits a report.
 *
 * Usage from frontend/:
 *   GEMINI_API_KEY=... npm run localize:gemini
 *   npm run localize:gemini -- --locales uk,ru,es --limit 50
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.join(__dirname, "..");
const REPO = path.join(FRONTEND, "..");
const LOCALES_DIR = path.join(FRONTEND, "locales");
const PUBLIC_DIR = path.join(FRONTEND, "public", "locales");
const REPORTS_DIR = path.join(REPO, "reports");
const REPORT_FILE = path.join(REPORTS_DIR, "localization_report.json");

const MODEL = normalizeModel(
  process.env.GEMINI_MODEL || process.env.GEMINI_TRANSLATION_MODEL || "gemini-flash-latest",
);
const API_VERSION = process.env.GEMINI_API_VERSION || "v1beta";
const BATCH_SIZE = clampInt(process.env.GEMINI_I18N_BATCH_SIZE, 20, { min: 1, max: 80 });
const BATCH_CHAR_BUDGET = clampInt(process.env.GEMINI_I18N_BATCH_CHARS, 18_000, { min: 2000, max: 80_000 });
const MAX_RETRIES = clampInt(process.env.GEMINI_I18N_MAX_RETRIES, 6, { min: 0, max: 12 });
const DRY = process.argv.includes("--dry-run");
const LIMIT_ARG = getArg("--limit");
const LIMIT = LIMIT_ARG ? Number(LIMIT_ARG) : 0;
const LOCALES_ARG = getArg("--locales");
const ONLY_LOCALES = LOCALES_ARG ? new Set(LOCALES_ARG.split(",").map((s) => s.trim()).filter(Boolean)) : null;

const LOCALE_NAMES = {
  ar: "Arabic", cs: "Czech", da: "Danish", de: "German", el: "Greek", es: "Spanish", fi: "Finnish",
  fr: "French", he: "Hebrew", hi: "Hindi", hu: "Hungarian", id: "Indonesian", it: "Italian",
  ja: "Japanese", ko: "Korean", nl: "Dutch", no: "Norwegian", pl: "Polish", pt: "Portuguese",
  ro: "Romanian", ru: "Russian", sv: "Swedish", th: "Thai", tr: "Turkish", uk: "Ukrainian",
  vi: "Vietnamese", "zh-CN": "Simplified Chinese", "zh-TW": "Traditional Chinese",
};

/** Keys or values that may stay English (brand, routes, provider names). */
function translationSkipReason(key, enVal) {
  if (key.startsWith("locale.") || key === "brand.name") return "locale_or_brand_key";
  const v = String(enVal ?? "").trim();
  if (!v) return "empty_en";
  if (/^https?:\/\//i.test(v)) return "url";
  if (/^\/[a-z0-9/_[\]-]+$/i.test(v) && v.length < 160) return "route_path";
  const standaloneBrand = new Set(["NEYRA", "Gemini", "Google", "Apple", "Facebook", "Premium"]);
  if (standaloneBrand.has(v)) return "brand_token";
  if (v === "OpenAI" || (v.endsWith("API") && v.length < 24)) return "technical_token";
  return null;
}

function getArg(name) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : null;
}

function clampInt(value, fallback, { min, max }) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, Math.trunc(n)));
}

function normalizeModel(model) {
  const raw = String(model || "").trim();
  if (!raw) return "gemini-flash-latest";
  return raw.replace(/^models\//i, "");
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function writeJson(file, data) {
  fs.writeFileSync(file, JSON.stringify(data, null, 2) + "\n", "utf8");
}

function writeJsonAtomic(file, data) {
  const dir = path.dirname(file);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  const tmp = path.join(dir, `.${path.basename(file)}.${process.pid}.${Date.now()}.tmp`);
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2) + "\n", "utf8");
  try {
    // Windows rename does not overwrite by default.
    if (fs.existsSync(file)) fs.rmSync(file);
    fs.renameSync(tmp, file);
  } catch (e) {
    try {
      if (fs.existsSync(tmp)) fs.rmSync(tmp);
    } catch {
      // ignore
    }
    throw e;
  }
}

function readDotEnv(file) {
  if (!fs.existsSync(file)) return {};
  const out = {};
  for (const raw of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const [k, ...rest] = line.split("=");
    out[k.trim()] = rest.join("=").trim().replace(/^['\"]|['\"]$/g, "");
  }
  return out;
}

function placeholders(s) {
  const str = String(s ?? "");
  const tokens = [];
  // {{name}} style
  for (const m of str.matchAll(/\{\{[^{}]+\}\}/g)) tokens.push(m[0]);
  // {count} style (including simple ICU variables)
  for (const m of str.matchAll(/\{[a-zA-Z0-9_.-]+\}/g)) tokens.push(m[0]);
  // printf-like: %s, %d, %1$s
  for (const m of str.matchAll(/%(?:\d+\$)?[sdif]/g)) tokens.push(m[0]);
  // Regex backrefs like $1 / $2 — but NOT currency like $7.99 ($7 followed by .digits).
  for (const m of str.matchAll(/\$\d+(?!\.\d)/g)) tokens.push(m[0]);
  // HTML-ish tags must remain unchanged (attributes too)
  for (const m of str.matchAll(/<\/?[A-Za-z][^>]*>/g)) tokens.push(m[0]);
  return tokens.sort();
}

function assertPlaceholders(key, source, translated) {
  const src = placeholders(source);
  const dst = placeholders(translated);
  const srcHasDollar = src.some((t) => /^\$\d+$/.test(t));
  // Only enforce $1/$2… backrefs if they exist in the English source.
  // This avoids false failures when the model introduces currency like "$2" for a price.
  const norm = (arr) => (srcHasDollar ? arr : arr.filter((t) => !/^\$\d+$/.test(t))).join("|");
  const a = norm(src);
  const b = norm(dst);
  if (a !== b) throw new Error(`Placeholder mismatch for ${key}: expected [${a}], got [${b}]`);
}

function stripCodeFence(text) {
  return String(text || "").trim().replace(/^```(?:json)?/i, "").replace(/```$/i, "").trim();
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function backoffMs(attempt) {
  const base = 900;
  const cap = 20_000;
  const exp = Math.min(cap, base * Math.pow(2, Math.max(0, attempt - 1)));
  const jitter = Math.random() * 250;
  return exp + jitter;
}

function shouldRetryStatus(status) {
  return status === 429 || status === 500 || status === 503;
}

function strictTranslatePrompt(localeName, locale, inputJson, { strict }) {
  const lines = [
    `You are localizing NEYRA, a premium AI dating app, into ${localeName} (${locale}).`,
    "Translate every value naturally for a modern product UI. Keep tone warm, premium, concise, and human.",
    "Never translate i18n keys. Never change routes, URLs, variable names, HTML tags, or placeholders.",
    "Preserve placeholders EXACTLY as-is (must match): {{name}}, {count}, %s, $1, and any <tag>...</tag> markup.",
    "Preserve emoji, punctuation intent, and line breaks.",
    strict
      ? "Return ONLY strict JSON (object). No markdown, no code fences, no explanations. Every key from input must exist in output."
      : "Return ONLY valid JSON: an object where keys are unchanged and values are translated strings.",
    "Input JSON:",
    inputJson,
  ];
  return lines.join("\n");
}

function tryParseJsonObject(text) {
  const stripped = stripCodeFence(text);
  const parsed = JSON.parse(stripped);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Gemini response JSON is not an object");
  }
  return parsed;
}

async function geminiTranslate(apiKey, locale, entries) {
  const localeName = LOCALE_NAMES[locale] || locale;
  const inputObj = Object.fromEntries(entries);
  const inputJson = JSON.stringify(inputObj, null, 2);

  const url = `https://generativelanguage.googleapis.com/${API_VERSION}/models/${MODEL}:generateContent?key=${encodeURIComponent(apiKey)}`;

  let lastErr = null;
  for (let attempt = 1; attempt <= Math.max(1, MAX_RETRIES + 1); attempt++) {
    const strict = attempt >= 2; // first retry becomes stricter if JSON was invalid
    const prompt = strictTranslatePrompt(localeName, locale, inputJson, { strict });

    let res;
    try {
      res = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          generationConfig: {
            temperature: 0.2,
            responseMimeType: "application/json",
          },
          contents: [{ role: "user", parts: [{ text: prompt }] }],
        }),
      });
    } catch (e) {
      lastErr = e;
      if (attempt <= MAX_RETRIES) {
        await sleep(backoffMs(attempt));
        continue;
      }
      throw e;
    }

    if (!res.ok) {
      const txt = await res.text();
      const err = new Error(`Gemini ${res.status}: ${txt}`);
      lastErr = err;
      if (attempt <= MAX_RETRIES && shouldRetryStatus(res.status)) {
        await sleep(backoffMs(attempt));
        continue;
      }
      throw err;
    }

    const body = await res.json();
    const text = body?.candidates?.[0]?.content?.parts?.map((p) => p.text || "").join("") || "";

    let parsed;
    try {
      parsed = tryParseJsonObject(text);
    } catch (e) {
      lastErr = e;
      if (attempt <= MAX_RETRIES) {
        await sleep(backoffMs(attempt));
        continue;
      }
      throw e;
    }

    // Validate keys and values
    for (const [key, source] of entries) {
      if (typeof parsed[key] !== "string" || !String(parsed[key]).trim()) {
        lastErr = new Error(`Missing translated value for ${key}`);
        parsed = null;
        break;
      }
      try {
        assertPlaceholders(key, source, parsed[key]);
      } catch (e) {
        lastErr = e;
        parsed = null;
        break;
      }
    }

    if (!parsed) {
      if (attempt <= MAX_RETRIES) {
        await sleep(backoffMs(attempt));
        continue;
      }
      throw lastErr || new Error("Gemini translation failed validation");
    }

    return parsed;
  }

  throw lastErr || new Error("Gemini translation failed");
}

const env = { ...readDotEnv(path.join(REPO, "backend", ".env")), ...process.env };
const apiKey = env.GEMINI_API_KEY;
if (!ONLY_LOCALES) {
  const example = "npm run localize:gemini -- --locales uk,ru,es,de,fr,it,pl,pt,hi,zh-CN,zh-TW,ar";
  console.log(
    [
      "localize:gemini (SAFE MODE)",
      "",
      "This script no longer defaults to translating every locale (to avoid accidental Gemini budget burn).",
      "",
      "Usage:",
      `  ${example}`,
      "",
      "Optional flags:",
      "  --limit N     translate only first N keys per locale (debug)",
      "  --dry-run     do not call Gemini; only report counts",
      "",
      "Notes:",
      "  - en.json is the source of truth",
      "  - existing non-English translations are preserved",
      "  - only missing/English-identical values are translated",
    ].join("\n"),
  );
  process.exit(1);
}
if (!apiKey && !DRY) {
  console.error("GEMINI_API_KEY is required. Put it in backend/.env or pass it as an environment variable.");
  process.exit(1);
}

const en = readJson(path.join(LOCALES_DIR, "en.json"));
const allLocaleFiles = fs.readdirSync(LOCALES_DIR).filter((f) => f.endsWith(".json") && f !== "en.json");
const existingLocaleSet = new Set(allLocaleFiles.map((f) => f.replace(/\.json$/, "")));
const localeCodes = [...ONLY_LOCALES]
  .map((s) => s.trim())
  .filter(Boolean)
  .filter((c) => c !== "en")
  .filter((c) => {
    if (existingLocaleSet.has(c)) return true;
    // One-time migration path: allow targeting zh-CN even if only legacy zh.json exists.
    if (c === "zh-CN" && existingLocaleSet.has("zh")) return true;
    return false;
  });
if (localeCodes.length === 0) {
  console.error("No valid --locales matched existing locale JSON files in frontend/locales/.");
  process.exit(1);
}
const startedAt = new Date().toISOString();
const report = {
  generated_at: startedAt,
  model: MODEL,
  dry_run: DRY,
  allowlist_note:
    "Skipped keys matching locale.* / brand.name, URLs, route paths, or standalone brand tokens (NEYRA, Gemini, …).",
  locales: {},
};

function makeBatches(entries, { maxKeys, charBudget }) {
  const batches = [];
  let cur = [];
  let curChars = 0;

  for (const [k, v] of entries) {
    const approx = k.length + String(v ?? "").length + 6;
    const wouldOverflow = cur.length > 0 && (cur.length + 1 > maxKeys || curChars + approx > charBudget);
    if (wouldOverflow) {
      batches.push(cur);
      cur = [];
      curChars = 0;
    }
    cur.push([k, v]);
    curChars += approx;
  }
  if (cur.length) batches.push(cur);
  return batches;
}

for (const locale of localeCodes) {
  const legacyLocaleFile =
    locale === "zh-CN" && !fs.existsSync(path.join(LOCALES_DIR, "zh-CN.json")) && fs.existsSync(path.join(LOCALES_DIR, "zh.json"))
      ? "zh"
      : locale;
  const file = path.join(LOCALES_DIR, `${legacyLocaleFile}.json`);
  const data = readJson(file);

  const candidates = Object.entries(en).filter(([key, enVal]) => {
    if (key.startsWith("locale.") || key === "brand.name") return true; // handled by skipReason below
    const v = data[key];
    if (v == null) return true;
    if (typeof v !== "string") return true;
    if (v.trim() === "") return true;
    return v === enVal;
  });
  let skippedAllowlisted = 0;
  const todo = candidates.filter(([key, value]) => {
    const r = translationSkipReason(key, value);
    if (r) {
      skippedAllowlisted += 1;
      return false;
    }
    return true;
  });
  const limited = LIMIT > 0 ? todo.slice(0, LIMIT) : todo;
  const totalKeys = Object.keys(en).length;
  report.locales[locale] = {
    total_keys: totalKeys,
    identical_to_en_count: candidates.length,
    skipped_allowlisted: skippedAllowlisted,
    queued_for_translation: todo.length,
    translated: 0,
    placeholder_mismatch_count: 0,
    failed_keys: [],
    remaining_equals_en: candidates.length,
  };
  console.log(
    `${locale}: ${candidates.length} missing/empty/identical-to-EN (${skippedAllowlisted} allowlisted skip) → ${todo.length} to translate${LIMIT ? `, limiting to ${limited.length}` : ""}`,
  );
  if (!limited.length) {
    continue;
  }
  if (DRY) {
    report.locales[locale].translated = 0;
    report.locales[locale].remaining_equals_en = candidates.length;
    continue;
  }

  const batches = makeBatches(limited, { maxKeys: BATCH_SIZE, charBudget: BATCH_CHAR_BUDGET });
  let done = 0;
  for (const batch of batches) {
    try {
      const translated = await geminiTranslate(apiKey, locale, batch);
      for (const [key] of batch) data[key] = translated[key];
      report.locales[locale].translated += batch.length;
      done += batch.length;
      console.log(`  ${locale}: ${done}/${limited.length}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      for (const [key] of batch) report.locales[locale].failed_keys.push(key);
      if (msg.toLowerCase().includes("placeholder")) {
        report.locales[locale].placeholder_mismatch_count += batch.length;
      }
      console.warn(`  ${locale}: batch failed (${batch.length} keys) — ${msg}`);
      // Keep run going: leave the English value for failed keys.
      // The report includes failed_keys + placeholder mismatch counts for follow-up.
      continue;
    }
  }

  writeJsonAtomic(path.join(LOCALES_DIR, `${locale}.json`), data);
  writeJsonAtomic(path.join(PUBLIC_DIR, `${locale}.json`), data);
  const after = Object.entries(en).filter(([key, value]) => data[key] === value && !key.startsWith("locale.") && key !== "brand.name")
    .length;
  report.locales[locale].remaining_equals_en = after;
}

fs.mkdirSync(REPORTS_DIR, { recursive: true });
writeJsonAtomic(REPORT_FILE, report);
console.log(`localize:gemini report written to ${path.relative(REPO, REPORT_FILE)}`);
