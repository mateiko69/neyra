import { LOCALES, type AppLocale } from "../i18n/locales";

export type OnboardingFormShape = {
  name: string;
  city: string;
  looking_for: string;
  vibe: string;
  interested_in: string;
  min_age: number;
  max_age: number;
  photos: string[];
  primaryIndex: number;
  gender: "man" | "woman" | "";
  date_of_birth: string;
  native_language: string;
  additional_languages: string[];
  tags: string[];
};

function parseCsv(s: string): string[] {
  return (s || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

function canonicalLocaleCode(raw: string): string {
  const s = String(raw || "").trim();
  if (!s) return "";
  const hit = LOCALES.find((l) => l.code.toLowerCase() === s.toLowerCase());
  return hit?.code ?? s;
}

/** Map stored profile gender to onboarding form values. */
export function genderToForm(raw: string): "man" | "woman" | "" {
  const s = (raw || "").trim().toLowerCase();
  if (s === "man" || s === "male" || s === "m") return "man";
  if (s === "woman" || s === "female" || s === "f") return "woman";
  return "";
}

function isoDateOnly(dob: unknown): string {
  if (dob == null) return "";
  if (typeof dob === "string") {
    const t = dob.trim();
    if (/^\d{4}-\d{2}-\d{2}/.test(t)) return t.slice(0, 10);
    return t;
  }
  return "";
}

/** Build partial form state from GET /profiles/me JSON (snake_case ProfileOut). */
export function profileToOnboardingFormPartial(profile: unknown): Partial<OnboardingFormShape> {
  if (!profile || typeof profile !== "object") return {};
  const p = profile as Record<string, unknown>;
  const out: Partial<OnboardingFormShape> = {};

  const name = String(p.display_name ?? "").trim();
  if (name) out.name = name;

  const city = String(p.city ?? "").trim();
  if (city) out.city = city;

  const g = genderToForm(String(p.gender ?? ""));
  if (g) out.gender = g;

  const dob = isoDateOnly(p.date_of_birth);
  if (dob) out.date_of_birth = dob;

  const looking = String(p.relationship_goal ?? "").trim();
  if (looking) out.looking_for = looking;

  const vibe = String(p.vibe ?? "").trim();
  if (vibe) out.vibe = vibe;

  const interested = String(p.interested_in ?? "").trim();
  if (interested) out.interested_in = interested;

  const mn = p.min_preferred_age;
  const mx = p.max_preferred_age;
  if (mn != null && mn !== "") {
    const n = Math.trunc(Number(mn));
    if (Number.isFinite(n) && n >= 18 && n <= 80) out.min_age = n;
  }
  if (mx != null && mx !== "") {
    const n = Math.trunc(Number(mx));
    if (Number.isFinite(n) && n >= 18 && n <= 80) out.max_age = n;
  }

  const native = canonicalLocaleCode(String(p.native_language ?? ""));
  if (native) out.native_language = native;

  const addLang = p.additional_languages;
  if (Array.isArray(addLang)) {
    out.additional_languages = addLang.map((x) => canonicalLocaleCode(String(x || ""))).filter(Boolean);
  } else {
    const langs = parseCsv(String(addLang ?? "")).map((x) => canonicalLocaleCode(x)).filter(Boolean);
    if (langs.length) out.additional_languages = langs;
  }

  const tagList = parseCsv(String(p.interests ?? ""));
  if (tagList.length) out.tags = tagList;

  const photos = parseCsv(String(p.photo_urls ?? ""));
  if (photos.length) {
    out.photos = photos;
    out.primaryIndex = 0;
  }

  return out;
}

export function emptyOnboardingForm(locale: AppLocale | string): OnboardingFormShape {
  const loc = String(locale || "").trim() || "en";
  return {
    name: "",
    city: "",
    looking_for: "",
    vibe: "",
    interested_in: "",
    min_age: 18,
    max_age: 35,
    photos: [],
    primaryIndex: 0,
    gender: "",
    date_of_birth: "",
    native_language: loc,
    additional_languages: [],
    tags: [],
  };
}
