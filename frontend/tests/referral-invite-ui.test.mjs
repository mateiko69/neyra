/**
 * Invite / referral reward UI wiring (static checks).
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const BACKEND_ROOT = path.join(ROOT, "..", "backend");

test("InviteFriendsCard maps rewards through t() (no visible API reward string)", () => {
  const card = path.join(ROOT, "app", "components", "InviteFriendsCard.tsx");
  const src = fs.readFileSync(card, "utf8");
  assert.match(src, /function nextRewardLabel/);
  assert.match(src, /function earnedRewardLabel/);
  assert.match(src, /nextRewardLabel\(t,\s*data\.next_reward\)/);
  assert.doesNotMatch(src, /next_reward\.reward[,\s}]/, "do not pass API reward English to UI text");
  assert.match(src, /t\("referrals\.reward\./);
});

test("Invite page uses t() for visible copy and enables reward UI", () => {
  const invite = path.join(ROOT, "app", "invite", "page.tsx");
  const src = fs.readFileSync(invite, "utf8");
  assert.match(src, /t\("referrals\.title"\)/);
  assert.match(src, /t\("referrals\.subtitle"\)/);
  assert.match(src, /InviteFriendsCard[^}]*showRewards/);
});

test("Telegram STRINGS uk/en include referral reward label keys", () => {
  const fp = path.join(BACKEND_ROOT, "scripts", "telegram_admin_bot.py");
  assert.ok(fs.existsSync(fp), fp);
  const src = fs.readFileSync(fp, "utf8");
  for (const key of ["growth_overview_referral_rewards", "premium_overview_referral_line"]) {
    const parts = src.split(`"${key}"`);
    assert.ok(parts.length >= 3, `expected "${key}" in both uk and en STRINGS (found ${parts.length - 1})`);
  }
});
