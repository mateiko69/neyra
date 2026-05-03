export type LocalAnalyticsEvent = {
  id: string;
  name: string;
  ts: number;
  payload: Record<string, unknown>;
};

const KEY_EVENTS = "neyra:analytics_events_v1";
const KEY_SESSION_ID = "neyra:analytics_session_id_v1";
const KEY_SESSION_STARTED = "neyra:analytics_session_started_v1";

const MAX_EVENTS = 2500;

function safeParse<T>(raw: string | null): T | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function now(): number {
  return Date.now();
}

function getSessionId(): string {
  try {
    const existing = sessionStorage.getItem(KEY_SESSION_ID);
    if (existing) return existing;
    const sid = `s:${now()}:${Math.random().toString(16).slice(2)}`;
    sessionStorage.setItem(KEY_SESSION_ID, sid);
    return sid;
  } catch {
    return `s:${now()}:na`;
  }
}

function ensureSessionStartRecorded(): void {
  try {
    if (sessionStorage.getItem(KEY_SESSION_STARTED) === "1") return;
    sessionStorage.setItem(KEY_SESSION_STARTED, "1");
    // Local-only event: do NOT send to backend.
    _append({
      id: `e:${now()}:${Math.random().toString(16).slice(2)}`,
      name: "local_session_started",
      ts: now(),
      payload: { session_id: getSessionId() },
    });
  } catch {
    // ignore
  }
}

function loadAll(): LocalAnalyticsEvent[] {
  try {
    const raw = localStorage.getItem(KEY_EVENTS);
    const parsed = safeParse<LocalAnalyticsEvent[]>(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((e) => e && typeof e.name === "string" && typeof e.ts === "number") as LocalAnalyticsEvent[];
  } catch {
    return [];
  }
}

function saveAll(events: LocalAnalyticsEvent[]): void {
  try {
    localStorage.setItem(KEY_EVENTS, JSON.stringify(events.slice(-MAX_EVENTS)));
  } catch {
    // ignore
  }
}

function _append(event: LocalAnalyticsEvent): void {
  const current = loadAll();
  current.push(event);
  saveAll(current);
}

export function recordLocalAnalyticsEvent(name: string, payload: Record<string, unknown> = {}): void {
  const eventName = String(name || "").trim();
  if (!eventName) return;
  ensureSessionStartRecorded();
  const event: LocalAnalyticsEvent = {
    id: `e:${now()}:${Math.random().toString(16).slice(2)}`,
    name: eventName,
    ts: now(),
    payload: { ...payload, _local_session_id: getSessionId() },
  };
  _append(event);
}

export function readLocalAnalyticsEvents(): LocalAnalyticsEvent[] {
  return loadAll().sort((a, b) => a.ts - b.ts);
}

export function clearLocalAnalyticsEvents(): void {
  try {
    localStorage.removeItem(KEY_EVENTS);
  } catch {}
}

