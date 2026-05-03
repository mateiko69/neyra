/**
 * Client-side dedupe for in-app retention signals (avoid repeating the same toast/day).
 */

export function utcDayKey(d = new Date()): string {
  return d.toISOString().slice(0, 10);
}

export function localStorageDayShown(storageKey: string, day = utcDayKey()): boolean {
  try {
    return localStorage.getItem(storageKey) === day;
  } catch {
    return false;
  }
}

export function localStorageMarkDay(storageKey: string, day = utcDayKey()): void {
  try {
    localStorage.setItem(storageKey, day);
  } catch {
    /* ignore */
  }
}

export function sessionShown(storageKey: string): boolean {
  try {
    return sessionStorage.getItem(storageKey) === "1";
  } catch {
    return false;
  }
}

export function sessionMark(storageKey: string): void {
  try {
    sessionStorage.setItem(storageKey, "1");
  } catch {
    /* ignore */
  }
}
