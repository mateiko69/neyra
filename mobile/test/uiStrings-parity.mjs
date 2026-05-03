/**
 * Ensures mobile/src/uiStrings.js en and uk maps define the same keys.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FILE = path.join(__dirname, "..", "src", "uiStrings.js");

function keysFromBlock(src, block) {
  const re = new RegExp(`${block}:\\s*\\{([\\s\\S]*?)\\n\\s*\\},`, "m");
  const m = src.match(re);
  assert.ok(m, `block ${block} not found`);
  const body = m[1];
  const out = [];
  for (const km of body.matchAll(/"([^"]+)":/g)) out.push(km[1]);
  return out.sort();
}

test("mobile uiStrings en/uk key parity", () => {
  const src = fs.readFileSync(FILE, "utf8");
  const enKeys = keysFromBlock(src, "en");
  const ukKeys = keysFromBlock(src, "uk");
  assert.deepEqual(ukKeys, enKeys);
});
