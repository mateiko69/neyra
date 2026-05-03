import type { AppLocale } from "./locales";

/** Canonical Latin / English city name → Ukrainian nominative (display in uk UI). */
const CITY_UK_NOMINATIVE: Record<string, string> = {
  Kyiv: "Київ",
  Kiev: "Київ",
  Lviv: "Львів",
  Kharkiv: "Харків",
  Odesa: "Одеса",
  Odessa: "Одеса",
  Dnipro: "Дніпро",
  Chernivtsi: "Чернівці",
  Verkhovyna: "Верховина",
  "Ivano-Frankivsk": "Івано-Франківськ",
};

/** Locative (в / у + city) for Ukrainian grammar — curated high-confidence forms. */
const CITY_UK_LOCATIVE: Record<string, string> = {
  Київ: "Києві",
  Львів: "Львові",
  Харків: "Харкові",
  Одеса: "Одесі",
  Дніпро: "Дніпрі",
  Чернівці: "Чернівцях",
  Верховина: "Верховині",
  "Івано-Франківськ": "Івано-Франківську",
};

function normalizeCityKey(city: string | null | undefined): string {
  return (city || "").trim();
}

/**
 * Display form of a city for the given UI locale.
 * Ukrainian uses official Ukrainian exonyms; other locales pass through trimmed Latin/UTF-8.
 */
export function getDisplayCity(city: string | null | undefined, locale: AppLocale): string {
  const c = normalizeCityKey(city);
  if (!c) return "";
  if (locale === "uk") {
    return CITY_UK_NOMINATIVE[c] ?? c;
  }
  return c;
}

/**
 * Ukrainian locative case for “in / at {city}” contexts (e.g. у Києві).
 * Non-Ukrainian locales return empty string (caller should use prepositions in copy).
 */
export function getCityLocative(city: string | null | undefined, locale: AppLocale): string {
  const c = normalizeCityKey(city);
  if (!c || locale !== "uk") return "";
  const nom = CITY_UK_NOMINATIVE[c] ?? c;
  return CITY_UK_LOCATIVE[nom] ?? nom;
}

/** e.g. "Kyiv, Ukraine" / "Київ, Україна" — extend country map as product grows. */
const COUNTRY_UK: Record<string, string> = {
  Ukraine: "Україна",
  UA: "Україна",
};

export function formatLocation(city: string | null | undefined, country: string | null | undefined, locale: AppLocale): string {
  const dc = getDisplayCity(city, locale);
  const co = (country || "").trim();
  if (!dc && !co) return "";
  if (locale === "uk") {
    const cUk = co ? COUNTRY_UK[co] ?? co : "";
    if (dc && cUk) return `${dc}, ${cUk}`;
    return dc || cUk;
  }
  if (dc && co) return `${dc}, ${co}`;
  return dc || co;
}
