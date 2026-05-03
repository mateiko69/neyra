/**
 * Single source of truth for supported locales. UI must never show translation keys like "locale.es".
 */

export type LocaleRow = {
  code: string;
  /** Native name for language selector */
  label: string;
  /** English name (admin / tooling) */
  labelEn: string;
  flag: string;
  rtl: boolean;
  /** Lower = earlier in "popular" ordering after current selection */
  popular: number;
};

export const LOCALES = [
  { code: "en", label: "English", labelEn: "English", flag: "🇺🇸", rtl: false, popular: 1 },
  { code: "uk", label: "Українська", labelEn: "Ukrainian", flag: "🇺🇦", rtl: false, popular: 2 },
  { code: "ru", label: "Русский", labelEn: "Russian", flag: "🇷🇺", rtl: false, popular: 3 },
  { code: "es", label: "Español", labelEn: "Spanish", flag: "🇪🇸", rtl: false, popular: 4 },
  { code: "pt", label: "Português", labelEn: "Portuguese", flag: "🇵🇹", rtl: false, popular: 5 },
  { code: "fr", label: "Français", labelEn: "French", flag: "🇫🇷", rtl: false, popular: 6 },
  { code: "de", label: "Deutsch", labelEn: "German", flag: "🇩🇪", rtl: false, popular: 7 },
  { code: "it", label: "Italiano", labelEn: "Italian", flag: "🇮🇹", rtl: false, popular: 8 },
  { code: "pl", label: "Polski", labelEn: "Polish", flag: "🇵🇱", rtl: false, popular: 9 },
  { code: "tr", label: "Türkçe", labelEn: "Turkish", flag: "🇹🇷", rtl: false, popular: 10 },
  { code: "zh-CN", label: "简体中文", labelEn: "Chinese (Simplified)", flag: "🇨🇳", rtl: false, popular: 11 },
  { code: "zh-TW", label: "繁體中文", labelEn: "Chinese (Traditional)", flag: "🇹🇼", rtl: false, popular: 12 },
  { code: "ja", label: "日本語", labelEn: "Japanese", flag: "🇯🇵", rtl: false, popular: 13 },
  { code: "ko", label: "한국어", labelEn: "Korean", flag: "🇰🇷", rtl: false, popular: 14 },
  { code: "hi", label: "हिन्दी", labelEn: "Hindi", flag: "🇮🇳", rtl: false, popular: 15 },
  { code: "id", label: "Bahasa Indonesia", labelEn: "Indonesian", flag: "🇮🇩", rtl: false, popular: 16 },
  { code: "vi", label: "Tiếng Việt", labelEn: "Vietnamese", flag: "🇻🇳", rtl: false, popular: 17 },
  { code: "th", label: "ไทย", labelEn: "Thai", flag: "🇹🇭", rtl: false, popular: 18 },
  { code: "ar", label: "العربية", labelEn: "Arabic", flag: "🇸🇦", rtl: true, popular: 19 },
  { code: "he", label: "עברית", labelEn: "Hebrew", flag: "🇮🇱", rtl: true, popular: 20 },
  { code: "bg", label: "Български", labelEn: "Bulgarian", flag: "🇧🇬", rtl: false, popular: 21 },
  { code: "nl", label: "Nederlands", labelEn: "Dutch", flag: "🇳🇱", rtl: false, popular: 40 },
  { code: "sv", label: "Svenska", labelEn: "Swedish", flag: "🇸🇪", rtl: false, popular: 41 },
  { code: "cs", label: "Čeština", labelEn: "Czech", flag: "🇨🇿", rtl: false, popular: 42 },
  { code: "ro", label: "Română", labelEn: "Romanian", flag: "🇷🇴", rtl: false, popular: 43 },
  { code: "hu", label: "Magyar", labelEn: "Hungarian", flag: "🇭🇺", rtl: false, popular: 44 },
  { code: "el", label: "Ελληνικά", labelEn: "Greek", flag: "🇬🇷", rtl: false, popular: 45 },
  { code: "da", label: "Dansk", labelEn: "Danish", flag: "🇩🇰", rtl: false, popular: 46 },
  { code: "fi", label: "Suomi", labelEn: "Finnish", flag: "🇫🇮", rtl: false, popular: 47 },
  { code: "no", label: "Norsk", labelEn: "Norwegian", flag: "🇳🇴", rtl: false, popular: 48 },
] as const satisfies readonly LocaleRow[];

export type AppLocale = (typeof LOCALES)[number]["code"];

export const SUPPORTED_LOCALE_CODES: readonly AppLocale[] = LOCALES.map((l) => l.code);

const BY_CODE: Record<string, (typeof LOCALES)[number]> = Object.fromEntries(LOCALES.map((l) => [l.code, l]));

const KNOWN_SET = new Set<string>(SUPPORTED_LOCALE_CODES);

export function isLocaleRtl(code: AppLocale): boolean {
  return Boolean(BY_CODE[code]?.rtl);
}

/** BCP 47 tags for Intl (plural rules, dates). */
export const INTL_LOCALE_BY_APP: Record<AppLocale, string> = {
  en: "en",
  uk: "uk",
  ru: "ru",
  es: "es",
  pt: "pt",
  fr: "fr",
  de: "de",
  it: "it",
  pl: "pl",
  tr: "tr",
  "zh-CN": "zh-Hans",
  "zh-TW": "zh-Hant",
  ja: "ja",
  ko: "ko",
  hi: "hi",
  id: "id",
  vi: "vi",
  th: "th",
  ar: "ar",
  he: "he",
  bg: "bg",
  nl: "nl",
  sv: "sv",
  cs: "cs",
  ro: "ro",
  hu: "hu",
  el: "el",
  da: "da",
  fi: "fi",
  no: "no",
};

/** HTML `lang` attribute. */
export const HTML_LANG_BY_APP: Record<AppLocale, string> = {
  en: "en",
  uk: "uk",
  ru: "ru",
  es: "es",
  pt: "pt",
  fr: "fr",
  de: "de",
  it: "it",
  pl: "pl",
  tr: "tr",
  "zh-CN": "zh-CN",
  "zh-TW": "zh-TW",
  ja: "ja",
  ko: "ko",
  hi: "hi",
  id: "id",
  vi: "vi",
  th: "th",
  ar: "ar",
  he: "he",
  bg: "bg",
  nl: "nl",
  sv: "sv",
  cs: "cs",
  ro: "ro",
  hu: "hu",
  el: "el",
  da: "da",
  fi: "fi",
  no: "no",
};

/**
 * Normalize browser / profile / stored strings to app locale codes.
 * zh-CN / zh-TW kept distinct; generic zh → zh-CN (Simplified).
 */
export function normalizeLocaleInput(raw: string | null | undefined): AppLocale | null {
  const value = (raw || "").trim().replace(/_/g, "-");
  if (!value) return null;
  const lower = value.toLowerCase();

  const alias: Record<string, AppLocale> = {
    "zh-cn": "zh-CN",
    "zh-hans": "zh-CN",
    "zh-sg": "zh-CN",
    "zh-tw": "zh-TW",
    "zh-hant": "zh-TW",
    "zh-hk": "zh-TW",
    "zh-mo": "zh-TW",
    "pt-br": "pt",
    "pt-pt": "pt",
    "en-us": "en",
    "en-gb": "en",
    "iw": "he",
    "he-il": "he",
    "nb": "no",
    "nn": "no",
  };

  if (alias[lower]) return alias[lower];

  if (lower === "zh") return "zh-CN";
  if (lower.startsWith("zh-")) {
    if (lower.includes("tw") || lower.includes("hant") || lower.includes("hk") || lower.includes("mo")) return "zh-TW";
    return "zh-CN";
  }

  if (lower.startsWith("pt")) return "pt";
  if (lower.startsWith("en")) return "en";

  const primary = lower.split("-")[0] || "";
  if (KNOWN_SET.has(primary)) return primary as AppLocale;

  if (KNOWN_SET.has(lower)) return lower as AppLocale;

  return null;
}

export function getLocaleRow(code: AppLocale): (typeof LOCALES)[number] | undefined {
  return BY_CODE[code];
}

/** Dropdown: flag + native name (never i18n keys or locale.* tokens). */
export function formatLocaleOptionLabel(code: AppLocale): string {
  const row = BY_CODE[code];
  if (!row) return humanizeI18nKey(String(code)) || String(code);
  return `${row.flag} ${row.label}`;
}

export function sortLocalesForSelect(selected: AppLocale, codes: readonly AppLocale[]): AppLocale[] {
  const unique = [...new Set(codes)];
  return unique.sort((a, b) => {
    if (a === selected && b !== selected) return -1;
    if (b === selected && a !== selected) return 1;
    const ra = BY_CODE[a]?.popular ?? 999;
    const rb = BY_CODE[b]?.popular ?? 999;
    if (ra !== rb) return ra - rb;
    const la = BY_CODE[a]?.label ?? a;
    const lb = BY_CODE[b]?.label ?? b;
    return la.localeCompare(lb, "en");
  });
}

/**
 * True if a string should never be shown as UI copy (raw locale code, nested key path, etc.).
 */
export function looksLikeRawI18nValue(value: string | null | undefined): boolean {
  const s = String(value ?? "").trim();
  if (!s) return true;
  if (/^locale\.[a-z]{2}(-[A-Z]{2})?$/i.test(s)) return true;
  if (s.startsWith("locale.") && s.length < 80) return true;
  if (/^[a-z][a-z0-9_]*\.[a-z][a-z0-9_.-]+$/i.test(s) && s.length < 96 && !s.includes(" ") && !s.includes(",")) {
    return true;
  }
  return false;
}

/** Last path segment of an i18n key → Title Case words (fallback label). */
export function humanizeI18nKey(key: string): string {
  const trimmed = (key || "").trim();
  const localePref = /^locale\.(.+)$/.exec(trimmed);
  if (localePref) {
    const code = localePref[1];
    const row = BY_CODE[code];
    if (row) return row.label;
  }
  const leaf = trimmed.split(".").pop() || trimmed || "";
  if (!leaf.trim()) return "";
  const spaced = leaf
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim();
  if (!spaced) return "";
  return spaced.replace(/\b\w/g, (c) => c.toUpperCase());
}
