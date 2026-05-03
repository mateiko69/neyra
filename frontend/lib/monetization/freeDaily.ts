type Stored = {
  dayKey: string;
  used: Record<string, number>;
};

const STORAGE_KEY = "neyra:free_daily:v1";

function utcDayKey(date: Date = new Date()): string {
  const y = date.getUTCFullYear();
  const m = String(date.getUTCMonth() + 1).padStart(2, "0");
  const d = String(date.getUTCDate()).padStart(2, "0");
  return `${y}${m}${d}`;
}

function safeParse(raw: string | null): Stored | null {
  if (!raw) return null;
  try {
    const j = JSON.parse(raw) as Partial<Stored>;
    if (!j || typeof j !== "object") return null;
    const dayKey = typeof j.dayKey === "string" ? j.dayKey : "";
    const used = j.used && typeof j.used === "object" ? (j.used as any) : {};
    if (!dayKey) return null;
    return { dayKey, used: used || {} };
  } catch {
    return null;
  }
}

function readStored(): Stored {
  const currentKey = utcDayKey();
  if (typeof window === "undefined") return { dayKey: currentKey, used: {} };
  const raw = safeParse(localStorage.getItem(STORAGE_KEY));
  if (!raw || raw.dayKey !== currentKey) {
    const fresh: Stored = { dayKey: currentKey, used: {} };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(fresh));
    } catch {
      /* ignore */
    }
    return fresh;
  }
  return raw;
}

function writeStored(next: Stored) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
}

export type FreeDailyFeature = "ai_opener" | "reveal" | "revive";

export function getFreeDailyUsed(feature: FreeDailyFeature): number {
  const s = readStored();
  const n = Number((s.used as any)?.[feature] ?? 0);
  return Number.isFinite(n) ? Math.max(0, Math.trunc(n)) : 0;
}

export function getFreeDailyLeft(feature: FreeDailyFeature, limit: number): number {
  const cap = Math.max(0, Math.trunc(limit));
  return Math.max(0, cap - getFreeDailyUsed(feature));
}

export function incrementFreeDailyUsed(feature: FreeDailyFeature, by: number = 1): number {
  const current = readStored();
  const prev = Number((current.used as any)?.[feature] ?? 0);
  const nextVal = (Number.isFinite(prev) ? Math.max(0, Math.trunc(prev)) : 0) + Math.max(0, Math.trunc(by));
  const next: Stored = { ...current, used: { ...(current.used || {}), [feature]: nextVal } };
  writeStored(next);
  return nextVal;
}

