/**
 * Bundled demo catalog photos live under /demo-profiles/{men|women}/<slug>/main.jpg
 * (served via backend static or Next public).
 */

const STRICT_DEMO_MAIN_RE = /^\/demo-profiles\/(men|women)\/[^/]+\/main\.jpg(\?.*)?$/i;

export function isBundledDemoMainPhotoPath(url: string): boolean {
  const u = String(url || "").trim();
  if (!u) return false;
  try {
    const path = u.startsWith("http://") || u.startsWith("https://") ? new URL(u).pathname : u.split("?")[0];
    return STRICT_DEMO_MAIN_RE.test(path || "");
  } catch {
    return false;
  }
}

/** Next N cards: first photo URL each, for decode preload. */
export function preloadDiscoverPhotoUrls(
  getPhotos: (card: { photo_urls?: unknown }) => string[],
  cards: { photo_urls?: unknown }[],
  startIndex: number,
  count: number,
): string[] {
  const out: string[] = [];
  const slice = cards.slice(startIndex, startIndex + count);
  for (const c of slice) {
    const p = getPhotos(c);
    if (p[0]) out.push(p[0]);
  }
  return out;
}
