import { debugChat } from "./chat/debug";
import type { NavBadgesResponse } from "./nav-config";

type Listener = () => void;

const listeners = new Set<Listener>();
const optimisticallyOpenedPartners = new Set<number>();

let snapshot: NavBadgesResponse | null = null;
let lastOptimisticAt = 0;

// Note: We intentionally avoid clamping server badge increases after optimistic updates.
// A quick increase may reflect a real incoming message on another device/session.

function safeCount(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return Math.max(0, Math.trunc(value));
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return Math.max(0, Math.trunc(parsed));
  }
  return 0;
}

function normalizeNavBadges(value: NavBadgesResponse | null): NavBadgesResponse | null {
  if (!value) return null;
  const newMatches = safeCount(value.new_matches);
  const incomingLikes = safeCount(value.incoming_likes);
  const matchesTotal = safeCount(value.matches);
  const attention =
    typeof value.matches_attention === "number" && Number.isFinite(value.matches_attention)
      ? safeCount(value.matches_attention)
      : incomingLikes + newMatches;
  return {
    unread_messages: safeCount(value.unread_messages),
    chat_threads_unread: safeCount(value.chat_threads_unread),
    new_matches: newMatches,
    incoming_likes: incomingLikes,
    matches: matchesTotal,
    matches_attention: attention,
  };
}

function emitChange() {
  listeners.forEach((listener) => listener());
}

export function subscribeNavBadges(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getNavBadgesSnapshot(): NavBadgesResponse | null {
  return snapshot;
}

export function setNavBadgesFromServer(next: NavBadgesResponse | null, reason: string): NavBadgesResponse | null {
  const normalized = normalizeNavBadges(next);
  snapshot = normalized;

  optimisticallyOpenedPartners.clear();
  debugChat("badge state after navigation refresh", { reason, badges: snapshot });
  emitChange();
  return snapshot;
}

export function clearNavBadgesStore(reason: string): void {
  snapshot = null;
  optimisticallyOpenedPartners.clear();
  debugChat("nav badges cleared", { reason });
  emitChange();
}

export function optimisticOpenThreadNavBadges(partnerUserId: number): NavBadgesResponse | null {
  const before = snapshot;
  debugChat("unread count before opening thread", { partnerUserId, badges: before });

  if (optimisticallyOpenedPartners.has(partnerUserId)) {
    debugChat("skip duplicate optimistic thread-open badge update", { partnerUserId, badges: before });
    return before;
  }

  // Record the intent even if badges haven't loaded yet; the next /nav/badges sync should reconcile.
  optimisticallyOpenedPartners.add(partnerUserId);
  lastOptimisticAt = Date.now();

  if (!before) return null;

  const nextThreadsUnread = Math.max(0, before.chat_threads_unread - 1);
  snapshot = {
    ...before,
    // We cannot safely subtract message counts without per-thread unread totals.
    // Keep unread_messages stable unless this was the last unread thread.
    unread_messages: nextThreadsUnread === 0 ? 0 : before.unread_messages,
    chat_threads_unread: nextThreadsUnread,
  };

  debugChat("optimistic nav badge update after thread open", {
    partnerUserId,
    before,
    after: snapshot,
  });

  emitChange();
  return snapshot;
}
