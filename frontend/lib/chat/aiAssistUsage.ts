type Stored = {
  dayKey: string;
  used: number;
};

const STORAGE_KEY = "neyra:ai_assist:usage:v1";

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
    const used = Number(j.used ?? 0);
    if (!dayKey) return null;
    if (!Number.isFinite(used) || used < 0) return null;
    return { dayKey, used: Math.trunc(used) };
  } catch {
    return null;
  }
}

function readStored(): Stored {
  if (typeof window === "undefined") return { dayKey: utcDayKey(), used: 0 };
  const currentKey = utcDayKey();
  const raw = safeParse(localStorage.getItem(STORAGE_KEY));
  if (!raw || raw.dayKey !== currentKey) {
    const fresh: Stored = { dayKey: currentKey, used: 0 };
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

export function getFreeAiAssistUsedToday(): number {
  return readStored().used;
}

export function incrementFreeAiAssistUsedToday(): number {
  const current = readStored();
  const next = { ...current, used: Math.max(0, current.used + 1) };
  writeStored(next);
  return next.used;
}

export function markLimitReached(limit: number = 5): number {
  const current = readStored();
  const next = { ...current, used: Math.max(0, Math.trunc(limit)) };
  writeStored(next);
  return next.used;
}

export function getFreeAiAssistsLeftToday(limit: number = 5): number {
  const used = getFreeAiAssistUsedToday();
  const cap = Math.max(0, Math.trunc(limit));
  return Math.max(0, cap - used);
}

