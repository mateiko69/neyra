import { normalizeLocaleInput, type AppLocale } from "./locales";

export type LocaleDetectionInput = {
  /** Server-stored profile locale (authoritative across devices). */
  profileLocale?: string | null;
  /** Local preference (manual language switch). */
  storedLocale?: string | null;
  /** Browser preferences (navigator.languages). */
  browserLanguages?: readonly string[] | null;
  /** Geo/IP hint. */
  geoLocale?: string | null;
};

export type LocaleDetectionResult = {
  locale: AppLocale;
  source: "profile" | "stored" | "browser" | "geo" | "fallback";
};

/**
 * Production-grade locale resolution with explicit priority:
 * 1) profileLocale
 * 2) storedLocale (manual switch)
 * 3) browserLanguages
 * 4) geoLocale
 * 5) fallback en
 *
 * Important nuance:
 * - We only *apply* profileLocale over storedLocale when storedLocale is empty.
 *   (If the user manually switched on this device, we never overwrite it.)
 */
export function resolvePreferredLocale(input: LocaleDetectionInput): LocaleDetectionResult {
  const stored = normalizeLocaleInput(input.storedLocale || null);
  if (stored) return { locale: stored, source: "stored" };

  const profile = normalizeLocaleInput(input.profileLocale || null);
  if (profile) return { locale: profile, source: "profile" };

  const langs = Array.isArray(input.browserLanguages) ? input.browserLanguages : [];
  for (const candidate of langs) {
    const loc = normalizeLocaleInput(candidate);
    if (loc) return { locale: loc, source: "browser" };
  }

  const geo = normalizeLocaleInput(input.geoLocale || null);
  if (geo) return { locale: geo, source: "geo" };

  return { locale: "en", source: "fallback" };
}

