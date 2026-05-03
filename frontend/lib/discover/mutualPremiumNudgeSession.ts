/**
 * Session-scoped limits for Discover "mutual likelihood" premium nudges (sessionStorage).
 */

const STORAGE_KEY = "neyra:discover_mutual_nudge:v1";

const MAX_SHOWS_PER_SESSION = 2;
/** First nudge only after the viewer has swiped a few times (less pushy on entry). */
const MIN_SWIPES_BEFORE_FIRST = 2;
/** Minimum swipes between the first and second nudge. */
const MIN_SWIPES_BETWEEN_NUDGES = 6;

type Stored = {
  count: number;
  userIds: number[];
  lastSwipeCount: number;
};

function defaultStored(): Stored {
  return { count: 0, userIds: [], lastSwipeCount: 0 };
}

function load(): Stored {
  if (typeof window === "undefined") return defaultStored();
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultStored();
    const o = JSON.parse(raw) as Partial<Stored>;
    const userIds = Array.isArray(o.userIds)
      ? o.userIds.map((x) => Math.trunc(Number(x))).filter((id) => Number.isFinite(id) && id > 0)
      : [];
    return {
      count: Math.max(0, Math.min(MAX_SHOWS_PER_SESSION, Math.trunc(Number(o.count) || 0))),
      userIds,
      lastSwipeCount: Math.max(0, Math.trunc(Number(o.lastSwipeCount) || 0)),
    };
  } catch {
    return defaultStored();
  }
}

function save(s: Stored): void {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(s));
  } catch {
    /* ignore */
  }
}

/** True if this session already committed a nudge slot for this candidate (e.g. React Strict Mode remount). */
export function mutualPremiumNudgeSessionHasUser(userId: number): boolean {
  const uid = Math.trunc(Number(userId));
  if (!Number.isFinite(uid) || uid < 1) return false;
  return load().userIds.includes(uid);
}

/**
 * If rules allow, records this show in the session and returns true.
 * Call at most once per top-card transition when you intend to display the nudge.
 */
export function tryAcquireMutualPremiumNudgeSession(userId: number, swipeCount: number): boolean {
  const uid = Math.trunc(Number(userId));
  if (!Number.isFinite(uid) || uid < 1) return false;
  const sw = Math.max(0, Math.trunc(Number(swipeCount) || 0));

  const state = load();
  if (state.count >= MAX_SHOWS_PER_SESSION) return false;
  if (state.userIds.includes(uid)) return false;

  if (state.count === 0) {
    if (sw < MIN_SWIPES_BEFORE_FIRST) return false;
  } else {
    if (sw - state.lastSwipeCount < MIN_SWIPES_BETWEEN_NUDGES) return false;
  }

  const next: Stored = {
    count: state.count + 1,
    userIds: [...state.userIds, uid],
    lastSwipeCount: sw,
  };
  save(next);
  return true;
}
