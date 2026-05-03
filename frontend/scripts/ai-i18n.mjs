/**
 * Dev workflow: ensure code keys exist in en.json, AI-fill uk/es/tr/zh gaps, sync public bundles.
 *
 * Requires Python + backend deps, OPENAI_API_KEY in backend/.env, and `python` on PATH.
 *
 * Usage: npm run ai-i18n
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.join(__dirname, "..");
const REPO = path.join(FRONTEND, "..");
const SYNC_PY = path.join(REPO, "sync_locales.py");

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, {
    encoding: "utf8",
    stdio: "inherit",
    cwd: opts.cwd ?? FRONTEND,
    shell: opts.shell ?? false,
  });
  if (r.status !== 0) {
    process.exit(r.status ?? 1);
  }
}

if (!fs.existsSync(SYNC_PY)) {
  console.error("Missing", SYNC_PY);
  process.exit(1);
}

run("npm", ["run", "check-i18n"], { cwd: FRONTEND });

const py = process.env.PYTHON ?? "python";
run(py, [SYNC_PY], { cwd: REPO });

run("npm", ["run", "sync-locales"], { cwd: FRONTEND });
run("npm", ["run", "check-i18n"], { cwd: FRONTEND });
run("npm", ["run", "test:i18n"], { cwd: FRONTEND });

console.log("ai-i18n: complete.");
