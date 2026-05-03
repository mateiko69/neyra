import test from "node:test";
import assert from "node:assert/strict";

import { dailyBoostsBannerView } from "../app/components/DailyBoostsBanner";

function t(key: string, vars?: Record<string, string | number>): string {
  if (vars && "count" in vars) return `${key}:${String(vars.count)}`;
  if (vars && "days" in vars) return `${key}:${String(vars.days)}:${String(vars.extra ?? "")}`;
  return key;
}

test("DailyBoostsBanner view: no boosts -> hidden, no chips", () => {
  const v = dailyBoostsBannerView(null as any, t);
  assert.equal(v.show, false);
  assert.deepEqual(v.chips, []);
  assert.equal(v.streakLine, null);
});

test("DailyBoostsBanner view: boosts -> visible with chips", () => {
  const v = dailyBoostsBannerView(
    {
      show_banner: true,
      opener_remaining: 1,
      reply_remaining: 2,
      reveal_remaining: 0,
      revive_remaining: 1,
      streak_days: 3,
      streak_bonus_ai_chat: 1,
    } as any,
    t,
  );
  assert.equal(v.show, true);
  assert.equal(v.chips.length >= 3, true);
  assert.equal(v.streakLine?.startsWith("dailyBoosts.streak.line"), true);
});

test("DailyBoostsBanner view: dismissed state hides banner", () => {
  const v = dailyBoostsBannerView(
    {
      show_banner: false,
      opener_remaining: 0,
      reply_remaining: 0,
      reveal_remaining: 0,
      revive_remaining: 0,
      streak_days: 0,
      streak_bonus_ai_chat: 0,
    } as any,
    t,
  );
  assert.equal(v.show, false);
});
