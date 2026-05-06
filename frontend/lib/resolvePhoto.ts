import { photosFromList, primaryPhotoFromList, resolveMediaUrl } from "./media";

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
    profile.demo_photo,
    profile.photoUrl,
    profile.imageUrl,
    profile.avatarUrl,
    profile.primaryPhotoUrl,
    profile.partnerPhoto,
    profile.partnerPhotoUrl,
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

function deriveDemoPath(profile: Record<string, unknown>, genderFolder: "men" | "women"): string | null {
  const demoFolder = toSlug(String(profile.demo_folder ?? profile.demoFolder ?? "").trim());
  if (demoFolder) return `/demo-profiles/${genderFolder}/${demoFolder}/main.jpg`;

  const idRaw = String(profile.id ?? profile.user_id ?? profile.userId ?? profile.partner_user_id ?? "").trim();
  const idLower = idRaw.toLowerCase();
  const match = idLower.match(/(?:man|woman)?_?demo_(\d{1,3})$/i);
  if (match?.[1]) {
    const padded = `demo_${match[1].padStart(3, "0")}`;
    return `/demo-profiles/${genderFolder}/${padded}/main.jpg`;
  }

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
  if (!profile || typeof profile !== "object") return "";
  const p = profile as Record<string, unknown>;
  const isDemo = Boolean(
    p.is_demo_profile ??
      p.isDemoProfile ??
      p.partner_is_demo_profile ??
      p.partnerIsDemoProfile ??
      p.is_demo ??
      p.isDemo ??
      String(p.demo_mode ?? "").trim() === "1",
  );
  const genderFolder = normalizeGenderFolder(p.gender ?? p.sex ?? p.partner_gender);
  const allCandidates = collectPhotoCandidates(p);

  for (const raw of allCandidates) {
    if (!raw) continue;
    if (isDemo && hasUploadsPath(raw)) continue;
    const resolved = resolveMediaUrl(raw);
    if (isDemo) {
      const pathOnly = resolved.startsWith("http://") || resolved.startsWith("https://") ? new URL(resolved).pathname : resolved;
      if (DEMO_MAIN_RE.test(pathOnly)) return pathOnly;
      continue;
    }
    if (resolved) return resolved;
  }

  if (isDemo) {
    const derived = deriveDemoPath(p, genderFolder);
    if (derived) return derived;
    return DEMO_FALLBACK_BY_GENDER[genderFolder];
  }

  return resolveMediaUrl(primaryPhotoFromList(allCandidates) || "");
}

export function resolvePhoto(profile: unknown): string {
  return resolveDemoProfilePhoto(profile);
}

