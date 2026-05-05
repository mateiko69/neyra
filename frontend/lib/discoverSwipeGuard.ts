export type DiscoverSwipeAction = "like" | "pass" | "ignore";

/** Short per-card lock to block double-submit; does not block the rest of the deck. */
export const DISCOVER_SWIPE_DEDUPE_MS = 650;

const pending = new Set<string>();
const recent = new Map<string, number>();

function swipeKey(candidateUserId: number, action: DiscoverSwipeAction): string {
  return `${Math.trunc(Number(candidateUserId))}:${action}`;
}

export function acquireDiscoverSwipe(candidateUserId: number, action: DiscoverSwipeAction, now = Date.now()): boolean {
  const id = Math.trunc(Number(candidateUserId));
  if (!Number.isFinite(id) || id <= 0) return false;
  const key = swipeKey(id, action);
  if (pending.has(key)) return false;
  const last = recent.get(key);
  if (typeof last === "number" && now - last < DISCOVER_SWIPE_DEDUPE_MS) return false;
  pending.add(key);
  recent.set(key, now);
  return true;
}

export function releaseDiscoverSwipe(candidateUserId: number, action: DiscoverSwipeAction): void {
  const id = Math.trunc(Number(candidateUserId));
  if (!Number.isFinite(id) || id <= 0) return;
  pending.delete(swipeKey(id, action));
}

export function clearDiscoverSwipeGuard(): void {
  pending.clear();
  recent.clear();
}
