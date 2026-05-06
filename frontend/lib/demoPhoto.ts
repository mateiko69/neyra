import { demoCatalogFallbackMain } from "./resolvePhoto";

type DemoProfileLike = Record<string, unknown>;

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

const KNOWN_DEMO_SLUGS = new Set(
  [
    "demo_001",
    "demo_002",
    "demo_003",
    "adam",
    "alex",
    "anna",
    "claire",
    "elena",
    "erik",
    "freja",
    "giulia",
    "leo",
    "mark",
    "maya",
    "milan",
    "nora",
    "oskar",
    "sofia",
    "tom",
  ].map((x) => x.toLowerCase()),
);

function extractDemoSlug(profile: DemoProfileLike): string {
  const direct = String(profile.demo_folder ?? profile.demoFolder ?? "").trim();
  if (direct) return toSlug(direct);

  const fromId = String(profile.id ?? profile.user_id ?? profile.userId ?? "").trim().toLowerCase();
  const m = fromId.match(/(?:^|[_/])demo[_-]?(\d{1,3})$/i);
  if (m?.[1]) return `demo_${m[1].padStart(3, "0")}`;

  const name = String(profile.display_name ?? profile.name ?? "").trim();
  const slug = toSlug(name);
  if (slug) return slug;
  return "";
}

/** Central demo bot photo resolver. Never returns an API-hosted URL. */
export function getDemoProfilePhoto(profile: unknown): string {
  if (!profile || typeof profile !== "object") return demoCatalogFallbackMain(null);
  const p = profile as DemoProfileLike;
  const gender = normalizeGenderFolder(p.gender ?? p.sex ?? p.partner_gender ?? p.partnerGender);
  const slug = extractDemoSlug(p);
  const safe = slug && KNOWN_DEMO_SLUGS.has(slug) ? slug : slug;
  if (safe) return `/demo-profiles/${gender}/${safe}/main.jpg`;
  return demoCatalogFallbackMain(gender);
}

