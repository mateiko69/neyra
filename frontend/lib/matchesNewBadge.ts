/** Fired after a successful POST /matches/mark-seen for a specific chat open (same-tab + listeners). */
export const MATCHES_MARK_SEEN_EVENT = "neyra:matches-mark-seen";

const STORAGE_KEY = "neyra:matches_new_dismissed_partners";

function readSet(): Set<number> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw) as unknown;
    if (!Array.isArray(arr)) return new Set();
    return new Set(arr.filter((x): x is number => typeof x === "number" && Number.isFinite(x)));
  } catch {
    return new Set();
  }
}

function writeSet(set: Set<number>): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...set].sort((a, b) => a - b)));
}

/** After mark-seen succeeds for an opened chat — hides "New" immediately when returning to Matches (handles refetch races). */
export function dismissMatchesNewBadgeForPartner(partnerUserId: number): void {
  if (typeof window === "undefined" || !Number.isFinite(partnerUserId)) return;
  const s = readSet();
  s.add(partnerUserId);
  writeSet(s);
  window.dispatchEvent(new CustomEvent(MATCHES_MARK_SEEN_EVENT, { detail: { partnerUserId } }));
}

export function isMatchesNewBadgeDismissedForPartner(partnerUserId: number): boolean {
  return readSet().has(partnerUserId);
}

/** Drop stored dismissals when the server already says the row is not new (keeps sessionStorage small). */
export function pruneDismissedMatchesNewBadges(
  matches: { partner_user_id: number; is_new_match?: boolean }[],
): void {
  if (typeof window === "undefined") return;
  const s = readSet();
  let changed = false;
  for (const m of matches) {
    if (!m.is_new_match && s.has(m.partner_user_id)) {
      s.delete(m.partner_user_id);
      changed = true;
    }
  }
  if (changed) writeSet(s);
}

export function clearMatchesNewBadgeDismissals(): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(STORAGE_KEY);
}
