import { photosFromList, primaryPhotoFromList, resolveMediaUrl } from "./media";

/**
 * Canonical "best photo" resolver for heterogeneous profile payloads.
 *
 * Priority:
 * - primary_photo_url
 * - photo_url
 * - avatar_url
 * - first photos[] / photo_urls[]
 * - fallback to empty string
 */
export function resolvePhoto(profile: unknown): string {
  if (!profile || typeof profile !== "object") return "";
  const p = profile as Record<string, unknown>;
  const direct =
    String((p.primary_photo_url ?? p.primaryPhotoUrl ?? p.primary_photo ?? p.primaryPhoto ?? "") || "").trim() ||
    String((p.photo_url ?? p.photoUrl ?? "") || "").trim() ||
    String((p.avatar_url ?? p.avatarUrl ?? "") || "").trim() ||
    String((p.partner_photo ?? p.partnerPhoto ?? "") || "").trim();
  if (direct) return resolveMediaUrl(direct);

  const list = photosFromList((p.photos ?? p.photo_urls ?? p.photoUrls ?? p.photo_urls_csv ?? p.photo_urls_text) as any);
  return resolveMediaUrl(primaryPhotoFromList(list) || "");
}

