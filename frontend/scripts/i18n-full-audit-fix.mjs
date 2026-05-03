import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const LOCALES_DIR = path.join(ROOT, "public", "locales");
const REPORTS_DIR = path.join(ROOT, "reports");
const SCAN_DIRS = [path.join(ROOT, "app"), path.join(ROOT, "lib"), path.join(ROOT, "components")];

const SKIP_DIRS = new Set(["node_modules", ".next", "dist", "coverage"]);
const CODE_EXT_RE = /\.(tsx?|jsx?)$/i;

function walkFiles(dir, out = []) {
  if (!fs.existsSync(dir)) return out;
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      if (SKIP_DIRS.has(ent.name)) continue;
      walkFiles(p, out);
    } else if (CODE_EXT_RE.test(ent.name)) {
      out.push(p);
    }
  }
  return out;
}

function readJson(p) {
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function writeJson(p, data) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(data, null, 2) + "\n", "utf8");
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function extractUsedKeys(source) {
  const out = new Set();
  const patterns = [/\bt\(\s*"([^"\\]+)"\s*[,)]/g, /\bt\(\s*'([^'\\]+)'\s*[,)]/g, /\bi18nKey\(\s*"([^"\\]+)"\s*[,)]/g];
  for (const re of patterns) {
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(source)) !== null) out.add(String(m[1]).trim());
  }
  return out;
}

function extractStringLiterals(source) {
  const out = [];
  const lines = source.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const jsxMatch = />([^<>{]{2,120})</g;
    let m;
    while ((m = jsxMatch.exec(line)) !== null) {
      const text = String(m[1] || "").trim();
      if (!text || /^[\d\s.,:;!?+=%/\-\\|]+$/.test(text)) continue;
      out.push({ line: i + 1, text, kind: "jsx" });
    }
    const quotedMatch = /\{\s*["']([^"'{}]{2,120})["']\s*\}/g;
    while ((m = quotedMatch.exec(line)) !== null) {
      const text = String(m[1] || "").trim();
      if (!text || /^[\d\s.,:;!?+=%/\-\\|]+$/.test(text)) continue;
      out.push({ line: i + 1, text, kind: "quoted" });
    }
  }
  return out;
}

function main() {
  const localeFiles = fs.readdirSync(LOCALES_DIR).filter((f) => f.endsWith(".json")).sort();
  const locales = Object.fromEntries(localeFiles.map((f) => [f.replace(/\.json$/, ""), readJson(path.join(LOCALES_DIR, f))]));
  const en = locales.en || {};
  const enKeys = Object.keys(en);

  // key -> locales missing
  const missingRows = [];
  for (const k of enKeys) {
    const missingIn = [];
    for (const [loc, data] of Object.entries(locales)) {
      if (!(k in data) || String(data[k] ?? "").trim() === "") missingIn.push(loc);
    }
    if (missingIn.length) missingRows.push({ key: k, missing_in: missingIn });
  }

  const files = SCAN_DIRS.flatMap((d) => walkFiles(d));
  const usedKeys = new Set();
  const hardcoded = [];
  const notUsedButExists = [];
  const fixes = [];

  // value -> key only if unique in EN
  const valueToUniqueKey = new Map();
  const dupValues = new Set();
  for (const [k, v] of Object.entries(en)) {
    if (typeof v !== "string") continue;
    const text = v.trim();
    if (!text) continue;
    if (valueToUniqueKey.has(text)) {
      dupValues.add(text);
      valueToUniqueKey.delete(text);
    } else if (!dupValues.has(text)) {
      valueToUniqueKey.set(text, k);
    }
  }

  for (const fp of files) {
    const rel = path.relative(ROOT, fp).replace(/\\/g, "/");
    const src = fs.readFileSync(fp, "utf8");
    for (const k of extractUsedKeys(src)) usedKeys.add(k);
    const literals = extractStringLiterals(src);
    for (const lit of literals) {
      hardcoded.push({ file: rel, line: lit.line, text: lit.text, kind: lit.kind });
      const k = valueToUniqueKey.get(lit.text);
      if (k) notUsedButExists.push({ file: rel, line: lit.line, text: lit.text, key: k });
    }

    // Safe auto-fix:
    // - file already uses useT and t(
    // - exact JSX text node match to unique EN value
    if (src.includes("useT(") && src.includes(" t(")) {
      let next = src;
      for (const [text, key] of valueToUniqueKey.entries()) {
        if (!text || text.length < 2) continue;
        const re = new RegExp(`>${escapeRegExp(text)}<`, "g");
        if (re.test(next)) {
          next = next.replace(re, `>{t("${key}")}<`);
        }
      }
      if (next !== src) {
        fs.writeFileSync(fp, next, "utf8");
        fixes.push(rel);
      }
    }
  }

  // keys in locales not referenced in code
  const unusedRows = enKeys.filter((k) => !usedKeys.has(k)).sort().map((key) => ({ key }));

  writeJson(path.join(REPORTS_DIR, "i18n_missing_keys_full.json"), missingRows);
  writeJson(path.join(REPORTS_DIR, "i18n_unused_keys_full.json"), unusedRows);
  writeJson(path.join(REPORTS_DIR, "i18n_not_used_but_exists.json"), notUsedButExists);
  writeJson(path.join(REPORTS_DIR, "i18n_autofix_applied.json"), fixes.map((file) => ({ file })));

  console.log(`[i18n-full-audit] files scanned: ${files.length}`);
  console.log(`[i18n-full-audit] missing rows: ${missingRows.length}`);
  console.log(`[i18n-full-audit] unused rows: ${unusedRows.length}`);
  console.log(`[i18n-full-audit] not_used_but_exists rows: ${notUsedButExists.length}`);
  console.log(`[i18n-full-audit] files auto-fixed: ${fixes.length}`);
}

main();
