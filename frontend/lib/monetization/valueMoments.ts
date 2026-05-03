/**
 * Client-side “value moments” for ethical paywall timing:
 * show stronger monetization only after the user has experienced core value
 * (incoming like, match, several AI assists, or sustained discover engagement).
 *
 * Stored in localStorage (persists across sessions; no PII).
 */

const K = {
  inboundLike: "neyra:vm:inbound_like",
  match: "neyra:vm:match",
  aiUses: "neyra:vm:ai_uses",
  outLikes: "neyra:vm:out_likes",
} as const;

function readBool(key: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function writeBool(key: string, v: boolean) {
  if (typeof window === "undefined") return;
  try {
    if (v) window.localStorage.setItem(key, "1");
  } catch {
    /* ignore */
  }
}

function readInt(key: string): number {
  if (typeof window === "undefined") return 0;
  try {
    const n = Number.parseInt(String(window.localStorage.getItem(key) || "0"), 10);
    return Number.isFinite(n) ? Math.max(0, n) : 0;
  } catch {
    return 0;
  }
}

function writeInt(key: string, n: number) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, String(Math.max(0, Math.trunc(n))));
  } catch {
    /* ignore */
  }
}

/** Someone liked you (waiting inbox) — value signal. */
export function recordInboundLikeMoment(): void {
  writeBool(K.inboundLike, true);
}

/** Mutual match from Discover (or elsewhere). */
export function recordMatchMoment(): void {
  writeBool(K.match, true);
}

/** Count outbound right-swipes / likes on Discover (engagement fallback). */
export function recordOutboundLikeMoment(): void {
  const n = readInt(K.outLikes) + 1;
  writeInt(K.outLikes, n);
}

/** Successful AI assist (copilot / reply pack generation). */
export function bumpAiUsageMoment(by = 1): void {
  const n = readInt(K.aiUses) + Math.max(1, Math.trunc(by));
  writeInt(K.aiUses, n);
}

export function hasValueMoment(): boolean {
  if (readBool(K.inboundLike) || readBool(K.match)) return true;
  if (readInt(K.aiUses) >= 3) return true;
  if (readInt(K.outLikes) >= 8) return true;
  return false;
}
