const STORAGE_PREFIX = "neyra:chatHeader:";

export type ChatThreadHeaderSeed = {
  displayName: string;
  avatarUrl: string | null;
};

export function setChatThreadHeaderSeed(partnerUserId: number, seed: ChatThreadHeaderSeed): void {
  if (typeof window === "undefined") return;
  try {
    const displayName = seed.displayName.trim();
    const avatarUrl = seed.avatarUrl?.trim() || null;
    if (!displayName && !avatarUrl) {
      sessionStorage.removeItem(`${STORAGE_PREFIX}${partnerUserId}`);
      return;
    }
    const payload: ChatThreadHeaderSeed = { displayName, avatarUrl };
    sessionStorage.setItem(`${STORAGE_PREFIX}${partnerUserId}`, JSON.stringify(payload));
  } catch {
    /* quota / private mode */
  }
}

export function getChatThreadHeaderSeed(partnerUserId: number): ChatThreadHeaderSeed | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(`${STORAGE_PREFIX}${partnerUserId}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ChatThreadHeaderSeed>;
    const displayName = typeof parsed.displayName === "string" ? parsed.displayName.trim() : "";
    const avatarUrl =
      typeof parsed.avatarUrl === "string" && parsed.avatarUrl.trim() ? parsed.avatarUrl.trim() : null;
    if (!displayName && !avatarUrl) return null;
    return { displayName, avatarUrl };
  } catch {
    return null;
  }
}
