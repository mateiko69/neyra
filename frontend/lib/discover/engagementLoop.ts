/**
 * Discover engagement loop: daily like counts, streaks, and micro-goals.
 * Persisted per user in localStorage. Backend sync can layer on via analytics or future API.
 */

export const DAILY_LIKES_FOR_BOOST = 5;

const STORAGE_PREFIX = "neyra:discover_engagement:v1";

type StoredStateV1 = {
  v: 1;
  /** Calendar day (local) that `todayLikes` refers to */
  likesDayKey: string;
  todayLikes: number;
  /** Last calendar day the user recorded a like (for streak) */
  lastLikeDayKey: string;
  streakDays: number;
};

function dayKey(d = new Date()): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function parseLocalDay(key: string): Date {
  const [y, m, d] = key.split("-").map((x) => Number(x));
  return new Date(y, m - 1, d);
}

/** Whole days from day key `a` to `b` (a before b → positive). */
function calendarDaysBetween(a: string, b: string): number {
  const ms = parseLocalDay(b).getTime() - parseLocalDay(a).getTime();
  return Math.round(ms / 86_400_000);
}

function keyForUser(userId: number): string {
  return `${STORAGE_PREFIX}:${userId}`;
}

function defaultState(): StoredStateV1 {
  const today = dayKey();
  return { v: 1, likesDayKey: today, todayLikes: 0, lastLikeDayKey: "", streakDays: 0 };
}

function loadRaw(userId: number): StoredStateV1 {
  if (typeof window === "undefined") return defaultState();
  try {
    const raw = localStorage.getItem(keyForUser(userId));
    if (!raw) return defaultState();
    const o = JSON.parse(raw) as Partial<StoredStateV1>;
    if (o?.v !== 1) return defaultState();
    return {
      v: 1,
      likesDayKey: String(o.likesDayKey || ""),
      todayLikes: Math.max(0, Math.trunc(Number(o.todayLikes) || 0)),
      lastLikeDayKey: String(o.lastLikeDayKey || ""),
      streakDays: Math.max(0, Math.trunc(Number(o.streakDays) || 0)),
    };
  } catch {
    return defaultState();
  }
}

function saveRaw(userId: number, s: StoredStateV1): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(keyForUser(userId), JSON.stringify(s));
  } catch {
    /* quota / private mode */
  }
}

function streakForDisplay(s: StoredStateV1, today: string): number {
  const last = s.lastLikeDayKey;
  if (!last) return 0;
  const diff = calendarDaysBetween(last, today);
  if (diff === 0) return Math.max(1, s.streakDays);
  if (diff === 1) return Math.max(1, s.streakDays);
  return 0;
}

export type DiscoverEngagementDisplay = {
  todayLikes: number;
  streakDays: number;
  likesForBoostRemaining: number;
  boostUnlocked: boolean;
  likesGoal: number;
};

export function getEngagementDisplay(userId: number): DiscoverEngagementDisplay {
  const today = dayKey();
  const s = loadRaw(userId);
  const todayLikes = s.likesDayKey === today ? s.todayLikes : 0;
  const streakDays = streakForDisplay(s, today);
  const likesGoal = DAILY_LIKES_FOR_BOOST;
  const boostUnlocked = todayLikes >= likesGoal;
  const likesForBoostRemaining = boostUnlocked ? 0 : Math.max(0, likesGoal - todayLikes);
  return { todayLikes, streakDays, likesForBoostRemaining, boostUnlocked, likesGoal };
}

/** Call after a successful like swipe (server accepted). Idempotent per swipe; counts each like. */
export function recordDiscoverLike(userId: number): void {
  const today = dayKey();
  let s = loadRaw(userId);

  if (s.likesDayKey !== today) {
    s = { ...s, likesDayKey: today, todayLikes: 0 };
  }

  s.todayLikes += 1;

  const last = s.lastLikeDayKey;
  if (!last) {
    s.streakDays = 1;
  } else if (last === today) {
    /* keep */
  } else {
    const diff = calendarDaysBetween(last, today);
    if (diff === 1) {
      s.streakDays = Math.max(1, s.streakDays) + 1;
    } else {
      s.streakDays = 1;
    }
  }
  s.lastLikeDayKey = today;

  saveRaw(userId, s);
}
