/** Short-lived client cache for the signed-in user's primary photo (e.g. chat thread header). */

const TTL_MS = 90_000;

type Entry = { fetchedAt: number; primary: string | null };

let entry: Entry | null = null;

export function peekMyPrimaryPhoto(now: number = Date.now()): string | null | undefined {
  if (!entry) return undefined;
  if (now - entry.fetchedAt > TTL_MS) return undefined;
  return entry.primary;
}

export function setMyPrimaryPhotoCache(primary: string | null, now: number = Date.now()) {
  entry = { fetchedAt: now, primary };
}

export function invalidateMyProfileAvatarCache() {
  entry = null;
}
