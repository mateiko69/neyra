/** localStorage flag: product intro (teaser) completed or skipped. */
export const INTRO_SEEN_STORAGE_KEY = "neyra:intro_seen";

export function isIntroSeen(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(INTRO_SEEN_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function markIntroSeen(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(INTRO_SEEN_STORAGE_KEY, "true");
  } catch {
    /* ignore */
  }
}
