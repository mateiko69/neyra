/**
 * App-level i18n config (paths, detection). Message loading stays in `lib/i18n`.
 */

import type { AppLocale } from "../../lib/i18n/locales";
import {
  HTML_LANG_BY_APP,
  LOCALES,
  normalizeLocaleInput,
  SUPPORTED_LOCALE_CODES,
  sortLocalesForSelect,
} from "../../lib/i18n/locales";

export const LOCALE_STORAGE_KEY = "neyra:locale" as const;

export type { AppLocale };

export { LOCALES, HTML_LANG_BY_APP, SUPPORTED_LOCALE_CODES, sortLocalesForSelect };

/** Map `navigator.language` / BCP-47 tag to a supported app locale; fallback `en`. */
export function detectBrowserAppLocale(): AppLocale {
  if (typeof navigator === "undefined") return "en";
  const candidates = [navigator.language, ...(navigator.languages || [])].filter(Boolean) as string[];
  for (const raw of candidates) {
    const normalized = normalizeLocaleInput(raw);
    if (normalized) return normalized;
  }
  return "en";
}

/** Apply `<html lang>` + `dir` for a locale (client-only). */
export function applyHtmlLangAttributes(locale: AppLocale): void {
  if (typeof document === "undefined") return;
  document.documentElement.lang = HTML_LANG_BY_APP[locale] ?? locale;
  const rtl = Boolean(LOCALES.find((l) => l.code === locale)?.rtl);
  document.documentElement.dir = rtl ? "rtl" : "ltr";
}
