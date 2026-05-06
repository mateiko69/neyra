import { photosFromList, primaryPhotoFromList, resolveMediaUrl } from "./media";
import { getDemoProfilePhoto } from "./demoPhoto";

const DEMO_MAIN_RE = /^\/demo-profiles\/(men|women)\/([^/]+)\/main\.jpg(?:\?.*)?$/i;

const DEMO_FALLBACK_BY_GENDER: Record<"men" | "women", string> = {
  men: "/demo-profiles/men/demo_001/main.jpg",
  women: "/demo-profiles/women/demo_001/main.jpg",
};

const DEMO_NAME_TO_FOLDER: Record<string, string> = {
  adam: "adam",
  alex: "alex",
  anna: "anna",
  claire: "claire",
  elena: "elena",
  erik: "erik",
  freja: "freja",
  giulia: "giulia",
  leo: "leo",
  mark: "mark",
  maya: "maya",
  milan: "milan",
  nora: "nora",
  oskar: "oskar",
  sofia: "sofia",
  tom: "tom",
};

function normalizeGenderFolder(raw: unknown): "men" | "women" {
  const value = String(raw ?? "").trim().toLowerCase();
  if (value === "man" || value === "men" || value === "male" || value === "m") return "men";
  return "women";
}

/** Bundled catalog fallback for Discover / matches when no URL resolves (demo MVP). */
export function demoCatalogFallbackMain(genderRaw: unknown): string {
  const folder = normalizeGenderFolder(genderRaw);
  return DEMO_FALLBACK_BY_GENDER[folder] ?? DEMO_FALLBACK_BY_GENDER.women;
}

/** Bundled JPG fallbacks — try preferred gender folder first, then the other (demo reliability). */
export function bundledDemoMainFallbackRing(genderRaw?: unknown): string[] {
  const folder = normalizeGenderFolder(genderRaw);
  const other: "men" | "women" = folder === "men" ? "women" : "men";
  return [DEMO_FALLBACK_BY_GENDER[folder], DEMO_FALLBACK_BY_GENDER[other]];
}

function toSlug(input: string): string {
  return String(input || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function hasUploadsPath(value: string): boolean {
  try {
    const path = value.startsWith("http://") || value.startsWith("https://") ? new URL(value).pathname : value;
    return path.startsWith("/uploads/");
  } catch {
    return value.startsWith("/uploads/");
  }
}

function collectPhotoCandidates(profile: Record<string, unknown>): string[] {
  const direct = [
    profile.photo_url,
    profile.image_url,
    profile.avatar_url,
    profile.primary_photo_url,
    profile.partner_photo,
    profile.partner_photo_url,
    profile.partner_avatar_url,
    profile.demo_photo,
    profile.photoUrl,
    profile.imageUrl,
    profile.avatarUrl,
    profile.primaryPhotoUrl,
    profile.partnerPhoto,
    profile.partnerPhotoUrl,
    profile.partnerAvatarUrl,
    profile.demoPhoto,
  ]
    .map((v) => String(v ?? "").trim())
    .filter(Boolean);
  const list = photosFromList(
    (profile.photos ??
      profile.photo_urls ??
      profile.photoUrls ??
      profile.photo_urls_csv ??
      profile.photo_urls_text ??
      profile.photo_urls_str) as any,
  );
  return [...direct, ...list.map((v) => String(v || "").trim()).filter(Boolean)];
}

/** Flatten nested partner_profile / partnerProfile so match rows resolve photos consistently. */
function mergePartnerProfileFields(profile: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = { ...profile };
  const nested = profile.partner_profile ?? profile.partnerProfile;
  if (nested && typeof nested === "object") {
    for (const [k, v] of Object.entries(nested as Record<string, unknown>)) {
      const cur = out[k];
      const empty = cur === undefined || cur === null || String(cur).trim() === "";
      if (empty && v !== undefined && v !== null) out[k] = v;
    }
  }
  return out;
}

// legacy helper kept for back-compat; prefer `getDemoProfilePhoto` from `demoPhoto.ts`.
function deriveDemoPath(profile: Record<string, unknown>, genderFolder: "men" | "women"): string | null {
  const demoFolder = toSlug(String(profile.demo_folder ?? profile.demoFolder ?? "").trim());
  if (demoFolder) return `/demo-profiles/${genderFolder}/${demoFolder}/main.jpg`;
  const name = toSlug(String(profile.display_name ?? profile.name ?? profile.partner_display_name ?? "").trim());
  if (name) {
    if (DEMO_NAME_TO_FOLDER[name]) return `/demo-profiles/${genderFolder}/${DEMO_NAME_TO_FOLDER[name]}/main.jpg`;
    return `/demo-profiles/${genderFolder}/${name}/main.jpg`;
  }
  return null;
}

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
export function resolveDemoProfilePhoto(profile: unknown): string {
  try {
    if (!profile || typeof profile !== "object") return DEMO_FALLBACK_BY_GENDER.women;
    const p = profile as Record<string, unknown>;
    const merged = mergePartnerProfileFields(p);
    const isDemo = Boolean(
      merged.is_demo_profile ??
        merged.isDemoProfile ??
        merged.partner_is_demo_profile ??
        merged.partnerIsDemoProfile ??
        merged.is_demo ??
        merged.isDemo ??
        String(merged.demo_mode ?? "").trim() === "1",
    );
    const genderFolder = normalizeGenderFolder(
      merged.gender ?? merged.sex ?? merged.partner_gender ?? merged.partnerGender,
    );
    const allCandidates = collectPhotoCandidates(merged);

    for (const raw of allCandidates) {
      if (!raw) continue;
      if (isDemo && hasUploadsPath(raw)) continue;
      const resolved = resolveMediaUrl(raw);
      if (isDemo) {
        let pathOnly = resolved;
        if (resolved.startsWith("http://") || resolved.startsWith("https://")) {
          try {
            pathOnly = new URL(resolved).pathname;
          } catch {
            pathOnly = resolved;
          }
        }
        if (DEMO_MAIN_RE.test(pathOnly)) return pathOnly;
        continue;
      }
      if (resolved) return resolved;
    }

    if (isDemo) {
      const derived = getDemoProfilePhoto({ ...merged, gender: merged.gender ?? genderFolder });
      if (derived) return derived;
      return DEMO_FALLBACK_BY_GENDER[genderFolder];
    }

    const last = resolveMediaUrl(primaryPhotoFromList(allCandidates) || "");
    if (last) return last;
    return DEMO_FALLBACK_BY_GENDER[genderFolder];
  } catch (error) {
    console.warn("discover card photo fallback used", { reason: "resolver_exception", error });
    return DEMO_FALLBACK_BY_GENDER.women;
  }
}

export function resolvePhoto(profile: unknown): string {
  return resolveDemoProfilePhoto(profile);
}

