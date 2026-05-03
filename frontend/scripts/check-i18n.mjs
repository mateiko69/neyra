/**
 * NEYRA i18n validation (dev & CI).
 *
 * Usage:
 *   npm run check-i18n
 *   npm run check-i18n -- --no-unused
 *   npm run check-i18n -- --no-hardcoded
 *   npm run check-i18n -- --no-parity      (skip locale structural + mirror summary)
 *   npm run check-i18n -- --parity-all     (mirror counts for every non-en locale)
 *   npm run check-i18n -- --strict-hardcoded
 *
 * Checks:
 *   1. Missing keys — t()/i18nKey() in app/ + lib/ vs locales/en.json
 *   2. Unused keys — en.json entries never referenced (heuristic; verify before delete)
 *   3. Hardcoded text — likely raw JSX/attr strings (heuristic)
 *   4. Locale parity — non-en bundles still mirroring English (info/warn)
 *
 * Exit 1 if missing keys in en.json (or --strict-hardcoded with hardcoded findings).
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const EN_PATH = path.join(ROOT, "locales", "en.json");
const LOCALES_DIR = path.join(ROOT, "locales");
const TRANSLATE_API = path.join(ROOT, "lib", "i18n", "translateApiUserMessage.ts");

const args = process.argv.slice(2);
const WANT_UNUSED = !args.includes("--no-unused");
const WANT_HARDCODED = !args.includes("--no-hardcoded");
const WANT_PARITY = !args.includes("--no-parity");
const PARITY_ALL = args.includes("--parity-all");
const STRICT_HARDCODED = args.includes("--strict-hardcoded");
const NO_COLOR = args.includes("--no-color") || process.env.NO_COLOR;

const c = NO_COLOR
  ? { reset: "", yellow: "", red: "", green: "", dim: "", bold: "" }
  : {
      reset: "\x1b[0m",
      yellow: "\x1b[33m",
      red: "\x1b[31m",
      green: "\x1b[32m",
      dim: "\x1b[2m",
      bold: "\x1b[1m",
    };

const SKIP_DIRS = new Set(["node_modules", ".next", "dist", "coverage", "__tests__"]);

const IMPLICIT_KEY_PATTERNS = [
  /^reportReason\./,
  /^onboarding\./,
  /^demo\.messages\./,
  /^demo\.live\./,
  /^people\.report\./,
  /^errors\.validation\.fields\./,
];

const UNUSED_PREFIX_ALLOWLIST = [
  "locale.",
  "errors.api.",
  "demo.messages.",
  "demo.live.",
  "referrals.reward.",
];

function walkFiles(dir, out = []) {
  if (!fs.existsSync(dir)) return out;
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      if (SKIP_DIRS.has(ent.name)) continue;
      walkFiles(p, out);
    } else {
      out.push(p);
    }
  }
  return out;
}

function readEn() {
  return JSON.parse(fs.readFileSync(EN_PATH, "utf8"));
}

function readEnKeys() {
  return new Set(Object.keys(readEn()));
}

function keysFromTranslateApi() {
  const src = fs.readFileSync(TRANSLATE_API, "utf8");
  const keys = new Set();
  const re = /["'](errors\.(?:api|validation)\.[a-zA-Z0-9_.]+)["']/g;
  let m;
  while ((m = re.exec(src)) !== null) {
    keys.add(m[1]);
  }
  return keys;
}

function extractTKeys(source) {
  const keys = new Set();
  const patterns = [
    /\bt\(\s*"([^"\\]+)"\s*[,)]/g,
    /\bt\(\s*'([^'\\]+)'\s*[,)]/g,
    /\bt\(\s*`([^`${}]+)`\s*[,)]/g,
    /\bi18nKey\(\s*"([^"\\]+)"\s*[,)]/g,
    /\bi18nKey\(\s*'([^'\\]+)'\s*[,)]/g,
    /(?:inspectI18nText|renderDebugText)\(\s*t\(\s*"([^"\\]+)"/g,
  ];
  for (const re of patterns) {
    let m;
    re.lastIndex = 0;
    while ((m = re.exec(source)) !== null) {
      const k = m[1].trim();
      if (!k || k.includes("${")) continue;
      keys.add(k);
    }
  }
  return keys;
}

/**
 * Heuristic hardcoded UI strings (not exhaustive).
 */
function scanHardcoded(filePath, source) {
  const findings = [];
  const lines = source.split("\n");
  const skipRe =
    /(\bt\(|i18nKey\(|className=|import |export |from ["']|http|localhost|aria-hidden|eslint|@apply|console\.|TODO|FIXME|\/\/|\/\*|\*\/|\sas\s|typeof\s|keyof\s|satisfies\s|Promise<|void\s|Record<)/i;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (skipRe.test(line)) continue;
    if (/^\s*\{/.test(line)) continue;

    const attr =
      /(?:placeholder|title|aria-label|alt)=\s*["']([^"'{}]{3,120})["']/.exec(line) ||
      /(?:placeholder|title|aria-label|alt)=\s*\{\s*["']([^"'{}]{3,120})["']\s*\}/.exec(line);
    if (attr && !/^[0-9]+$/.test(attr[1]) && /[a-zA-Z]{2,}/.test(attr[1])) {
      findings.push({ line: i + 1, kind: "attr", text: attr[1].slice(0, 80), file: filePath });
      continue;
    }

    // Avoid false positives on TS/JS comparisons like `>=` and `<=` (they contain `>` and `<`).
    // Comparisons typically have `>=` so the char immediately after `>` is `=`.
    const jsxText = />(?![=])\s*([^<>{][^<]{2,80})\s*</.exec(line);
    if (jsxText) {
      const text = jsxText[1].trim();
      // Skip common TS/JS comparison / expression artifacts (not user-facing strings).
      if (
        /^\d+\s*&&\s*/.test(text) ||
        text.includes("Date.now") ||
        text.includes(".length") ||
        text.includes("draftPart: Partial") ||
        /^[a-zA-Z_$][a-zA-Z0-9_$]*\.length$/.test(text)
      ) {
        continue;
      }
      if (/^[\d\s.,:;!?+=%\-/\\|]+$/.test(text)) continue;
      if (text.length < 3 || text.length > 80) continue;
      if (/^\s*\$/.test(text)) continue;
      if (/^(true|false|null|undefined|void|Promise)$/i.test(text)) continue;
      findings.push({ line: i + 1, kind: "jsx", text, file: filePath });
    }
  }
  return findings;
}

function sectionTitle(title) {
  console.log(`\n${c.bold}[i18n] ${title}${c.reset}`);
}

function warnLine(msg) {
  console.log(`${c.yellow}  ⚠${c.reset} ${msg}`);
}

function okLine(msg) {
  console.log(`${c.green}  ✓${c.reset} ${msg}`);
}

function errLine(msg) {
  console.log(`${c.red}  ✖${c.reset} ${msg}`);
}

const DEFAULT_MIRROR_LOCALES = new Set(["uk.json", "es.json", "tr.json", "zh-CN.json", "zh-TW.json"]);

/**
 * Non-en locale files: structural missing keys; optional English-mirror counts.
 */
function localeParityReport(enObj, { mirrorAllFiles }) {
  const enKeys = Object.keys(enObj);
  const files = fs.readdirSync(LOCALES_DIR).filter((f) => f.endsWith(".json") && f !== "en.json");
  const reports = [];

  for (const f of files.sort()) {
    const p = path.join(LOCALES_DIR, f);
    let data;
    try {
      data = JSON.parse(fs.readFileSync(p, "utf8"));
    } catch {
      reports.push({ file: f, error: "invalid JSON" });
      continue;
    }
    const missingKeys = enKeys.filter((k) => !(k in data));
    let mirror = 0;
    const examples = [];
    const countMirror = mirrorAllFiles || DEFAULT_MIRROR_LOCALES.has(f);
    if (countMirror) {
      for (const key of enKeys) {
        if (key.startsWith("locale.")) continue;
        const ev = enObj[key];
        const lv = data[key];
        if (typeof ev !== "string" || typeof lv !== "string") continue;
        if (!ev.trim()) continue;
        if (lv === ev) {
          mirror++;
          if (examples.length < 4) examples.push(key);
        }
      }
    }
    reports.push({ file: f, mirror, examples, missing: missingKeys.length, missingKeys });
  }
  return reports;
}

function main() {
  if (!fs.existsSync(EN_PATH)) {
    errLine(`Missing master bundle: ${EN_PATH}`);
    process.exit(1);
  }

  const enObj = readEn();
  const enKeys = new Set(Object.keys(enObj));
  const used = new Set(keysFromTranslateApi());

  for (const IMPLICIT of IMPLICIT_KEY_PATTERNS) {
    for (const k of enKeys) {
      if (IMPLICIT.test(k)) used.add(k);
    }
  }

  const scanRoots = [path.join(ROOT, "app"), path.join(ROOT, "lib")];
  const files = scanRoots.flatMap((d) => walkFiles(d)).filter((f) => /\.(tsx|ts)$/.test(f) && !f.endsWith(".d.ts"));

  for (const file of files) {
    const src = fs.readFileSync(file, "utf8");
    for (const k of extractTKeys(src)) {
      used.add(k);
    }
  }

  console.log(`${c.bold}${c.dim}NEYRA i18n validation${c.reset}`);

  // --- Missing keys (error) ---
  sectionTitle("1. Missing keys (code → en.json)");
  const missing = [...used].filter((k) => !enKeys.has(k)).sort();
  if (missing.length) {
    errLine(`${missing.length} key(s) referenced in code but missing from locales/en.json:`);
    for (const k of missing.slice(0, 200)) console.log(`      ${c.red}${k}${c.reset}`);
    if (missing.length > 200) console.log(`      ${c.dim}… and ${missing.length - 200} more${c.reset}`);
  } else {
    okLine("No missing keys.");
  }

  // --- Unused keys (warning) ---
  if (WANT_UNUSED) {
    sectionTitle("2. Possibly unused keys (en.json → code scan)");
    const unused = [...enKeys]
      .filter((k) => !used.has(k) && !UNUSED_PREFIX_ALLOWLIST.some((p) => k.startsWith(p)))
      .sort();
    if (unused.length) {
      warnLine(`${unused.length} key(s) in en.json not seen in static t()/i18nKey() scan — verify before deleting:`);
      for (const k of unused.slice(0, 120)) console.log(`      ${c.yellow}${k}${c.reset}`);
      if (unused.length > 120) console.log(`      ${c.dim}… and ${unused.length - 120} more${c.reset}`);
    } else {
      okLine("No unused-key suspects (within heuristic).");
    }
  } else {
    sectionTitle("2. Unused keys");
    console.log(`${c.dim}  (skipped: --no-unused)${c.reset}`);
  }

  // --- Hardcoded (warning) ---
  let hardcodedCount = 0;
  if (WANT_HARDCODED) {
    sectionTitle("3. Hardcoded text suspects (heuristic)");
    const tsxFiles = files.filter((f) => f.endsWith(".tsx"));
    const all = [];
    for (const file of tsxFiles) {
      const src = fs.readFileSync(file, "utf8");
      all.push(...scanHardcoded(file, src));
    }
    hardcodedCount = all.length;
    if (all.length) {
      warnLine(`${all.length} finding(s) — consider t("...") or attrs from i18n:`);
      for (const h of all.slice(0, 150)) {
        const rel = path.relative(ROOT, h.file);
        console.log(`      ${c.dim}${rel}:${h.line}${c.reset} [${h.kind}] ${JSON.stringify(h.text)}`);
      }
      if (all.length > 150) console.log(`      ${c.dim}… and ${all.length - 150} more${c.reset}`);
    } else {
      okLine("No hardcoded suspects (within heuristic).");
    }
  } else {
    sectionTitle("3. Hardcoded text");
    console.log(`${c.dim}  (skipped: --no-hardcoded)${c.reset}`);
  }

  // --- Locale parity ---
  if (WANT_PARITY) {
    sectionTitle("4. Locale bundles (structural + EN-mirror hint)");
    const reports = localeParityReport(enObj, { mirrorAllFiles: PARITY_ALL });
    let hadIssue = false;
    for (const r of reports) {
      if (r.error) {
        warnLine(`${r.file}: ${r.error}`);
        hadIssue = true;
        continue;
      }
      if (r.missing > 0) {
        errLine(`${r.file}: ${r.missing} key(s) missing vs en.json — run: npm run sync-locales`);
        for (const k of r.missingKeys.slice(0, 12)) console.log(`      ${c.red}${k}${c.reset}`);
        if (r.missingKeys.length > 12) console.log(`      ${c.dim}… +${r.missingKeys.length - 12} more${c.reset}`);
        hadIssue = true;
      }
    }
    const mirrorNote = PARITY_ALL ? "all non-en locales" : "uk / es / tr / zh only (use --parity-all for every locale)";
    console.log(`  ${c.dim}EN-mirror counts (${mirrorNote}):${c.reset}`);
    for (const r of reports) {
      if (r.error || !("mirror" in r)) continue;
      if (!PARITY_ALL && !DEFAULT_MIRROR_LOCALES.has(r.file)) continue;
      if (r.mirror > 0) {
        const ex =
          r.examples.length > 0 ? `e.g. ${r.examples.slice(0, 3).join(", ")}` : "examples: (none listed)";
        warnLine(`${r.file}: ${r.mirror} non-locale.* string(s) identical to English — ${ex}`);
        hadIssue = true;
      } else if (!PARITY_ALL && DEFAULT_MIRROR_LOCALES.has(r.file)) {
        console.log(`      ${c.dim}${r.file}: 0 EN-mirror suspects (excluding locale.*)${c.reset}`);
      }
    }
    if (!hadIssue) {
      okLine("No missing keys in locale files; mirror check clean for reported locales.");
    }
  } else {
    sectionTitle("4. Translation parity");
    console.log(`${c.dim}  (skipped: --no-parity)${c.reset}`);
  }

  console.log("");

  let exit = 0;
  if (missing.length) exit = 1;
  if (STRICT_HARDCODED && WANT_HARDCODED && hardcodedCount > 0) exit = 1;

  if (exit === 0) {
    console.log(`${c.green}${c.bold}[i18n] OK${c.reset} — no blocking issues.\n`);
  } else {
    console.log(`${c.red}${c.bold}[i18n] FAILED${c.reset} — fix missing keys or run with stricter rules.\n`);
  }

  process.exit(exit);
}

main();
