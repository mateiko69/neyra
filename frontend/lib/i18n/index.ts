"use client";

import { useCallback, useLayoutEffect, useMemo, useSyncExternalStore } from "react";
import { apiFetch, getToken, invalidateApiGetCache } from "../api";
import { clearAiSuggestionCaches } from "../aiSuggestionCache";
import {
  neyraAiLocaleChanged,
  neyraAiLocaleClearingSuggestedRepliesCache,
  neyraAiLocaleDevLog,
} from "../chat/neyraAiLocaleLog";
import enMessages from "../../locales/en.json";
import { ONBOARDING_MESSAGE_OVERRIDES } from "../../locales/onboarding.overrides";
import { fetchGeoOnce } from "./geo";
import { resolvePreferredLocale } from "./detect";
import {
  type AppLocale,
  HTML_LANG_BY_APP,
  INTL_LOCALE_BY_APP,
  LOCALES,
  humanizeI18nKey,
  isLocaleRtl,
  looksLikeRawI18nValue,
  normalizeLocaleInput,
  SUPPORTED_LOCALE_CODES,
} from "./locales";

export type Locale = AppLocale;
/** @deprecated Prefer `Locale`; kept for older imports that assumed a short allow-list. */
export type SupportedUiLocale = Locale;
export const SUPPORTED_LOCALES = SUPPORTED_LOCALE_CODES;

export {
  LOCALES,
  formatLocaleOptionLabel,
  getLocaleRow,
  humanizeI18nKey,
  isLocaleRtl,
  looksLikeRawI18nValue,
  normalizeLocaleInput,
  sortLocalesForSelect,
} from "./locales";

export { fetchGeoOnce, NEYRA_GEO_STORAGE_KEY, type NeyraGeoPayload } from "./geo";

export { formatLocation, getCityLocative, getDisplayCity } from "./cities";

export type TranslationVars = Record<string, string | number>;

const STORAGE_KEY = "neyra:locale";
const DEFAULT_LOCALE: Locale = "en";
const I18N_DEBUG_ENV = (process.env.NEXT_PUBLIC_I18N_DEBUG ?? "").trim().toLowerCase();
const I18N_DEBUG = I18N_DEBUG_ENV === "1" || I18N_DEBUG_ENV === "true";
const I18N_AI_ENV = (process.env.NEXT_PUBLIC_I18N_AI ?? "").trim().toLowerCase();
const I18N_AI_ENABLED = I18N_AI_ENV === "1" || I18N_AI_ENV === "true";
const I18N_AI_ENDPOINT = (process.env.NEXT_PUBLIC_I18N_AI_ENDPOINT ?? "").trim();
const I18N_AI_CACHE_KEY = "neyra:i18n:ai-cache:v1";
const I18N_META_OPEN = "\u2063\u2060";
const I18N_META_CLOSE = "\u2060\u2063";
const IS_DEV = process.env.NODE_ENV === "development";

type MessageDict = Record<string, string>;

const EN_MESSAGES = enMessages as MessageDict;

/** Overlay loaded from `/locales/{code}.json` (and AI cache merge). English base is always `EN_MESSAGES`. */
const localeOverlays: Partial<Record<Locale, MessageDict>> = {};
const localeFetchDone = new Set<Locale>();
const localeFetchInflight = new Map<Locale, Promise<void>>();

type I18nSnapshot = {
  ready: boolean;
  locale: Locale;
  messages: MessageDict;
  debug: boolean;
};

const listeners = new Set<() => void>();
const missingTranslationWarnings = new Set<string>();
const aiRequestedKeys = new Set<string>();

let localeInitialized = false;
let snapshot: I18nSnapshot = {
  ready: true,
  locale: DEFAULT_LOCALE,
  messages: buildMessages(DEFAULT_LOCALE),
  debug: I18N_DEBUG,
};

function normalizeLocale(raw: string | null | undefined): Locale | null {
  return normalizeLocaleInput(raw);
}

/** Normalize raw input to a supported app {@link Locale}, or `null` if unknown. */
export function normalizeToSupportedUiLocale(raw: string | null | undefined): Locale | null {
  return normalizeLocaleInput(raw);
}

function buildMessages(locale: Locale): MessageDict {
  const overlayRaw = localeOverlays[locale] ?? {};
  const overlay: MessageDict = {};
  for (const [k, v] of Object.entries(overlayRaw)) {
    if (typeof v !== "string") continue;
    if (!v.trim()) continue;
    if (looksLikeRawI18nValue(v)) continue;
    overlay[k] = v;
  }
  const overrides = ONBOARDING_MESSAGE_OVERRIDES[locale as keyof typeof ONBOARDING_MESSAGE_OVERRIDES];
  return { ...EN_MESSAGES, ...overlay, ...(overrides ?? {}) };
}

function guessLocaleFromBrowser(): Locale | null {
  if (typeof navigator === "undefined") return null;
  const langs = Array.isArray(navigator.languages) && navigator.languages.length ? navigator.languages : [navigator.language];
  for (const candidate of langs) {
    const loc = normalizeLocale(candidate);
    if (loc) return loc;
  }
  return null;
}

function applyDocumentLocale(locale: Locale) {
  if (typeof document === "undefined") return;
  document.documentElement.lang = HTML_LANG_BY_APP[locale] ?? locale;
  document.documentElement.dir = isLocaleRtl(locale) ? "rtl" : "ltr";
}

async function guessLocaleFromIp(): Promise<Locale | null> {
  if (typeof window === "undefined") return null;
  const g = await fetchGeoOnce();
  if (!g?.locale) return null;
  return normalizeLocale(g.locale);
}

export type I18nState = {
  locale: Locale;
  messages: MessageDict;
};

function emitChange() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot() {
  return snapshot;
}

function getServerSnapshot() {
  return snapshot;
}

function applyLocale(next: Locale, ready: boolean) {
  snapshot = {
    ...snapshot,
    ready,
    locale: next,
    messages: buildMessages(next),
  };
  applyDocumentLocale(next);
}

function warnMissingTranslationWithScope(locale: Locale, key: string, scope?: string) {
  const warningKey = `${locale}:${key}`;
  if (missingTranslationWarnings.has(warningKey)) return;
  missingTranslationWarnings.add(warningKey);
  const scopeSuffix = scope ? ` in ${scope}` : "";
  const msg = `[neyra:i18n] missing translation key "${key}" for locale "${locale}"${scopeSuffix} — using English/humanized fallback`;
  console.warn(msg);
}

function encodeI18nMetadata(key: string, missing: boolean, value: string): string {
  if (!I18N_DEBUG) return value;
  return `${I18N_META_OPEN}${missing ? "missing" : "ok"}:${key}${I18N_META_CLOSE}${value}`;
}

function interpolateTranslation(base: string, vars?: TranslationVars): string {
  if (!vars) return base;
  return Object.keys(vars).reduce((acc, name) => {
    const token = `{${name}}`;
    return acc.split(token).join(String(vars[name]));
  }, base);
}

export function isI18nDebugEnabled(): boolean {
  return I18N_DEBUG;
}

export function readI18nDebugMetadata(value: string | null | undefined): {
  key: string;
  missing: boolean;
  text: string;
} | null {
  if (!value || !value.startsWith(I18N_META_OPEN)) return null;
  const closeIndex = value.indexOf(I18N_META_CLOSE, I18N_META_OPEN.length);
  if (closeIndex === -1) return null;

  const payload = value.slice(I18N_META_OPEN.length, closeIndex);
  const separatorIndex = payload.indexOf(":");
  if (separatorIndex <= 0) return null;

  const status = payload.slice(0, separatorIndex);
  const key = payload.slice(separatorIndex + 1);
  if (!key) return null;

  return {
    key,
    missing: status === "missing",
    text: value.slice(closeIndex + I18N_META_CLOSE.length),
  };
}

export function stripI18nDebugMetadata(value: string | null | undefined): string {
  const meta = readI18nDebugMetadata(value);
  return meta?.text ?? (value ?? "");
}

function pluralCategory(locale: Locale, count: number): string {
  const tag = INTL_LOCALE_BY_APP[locale] ?? "en";
  try {
    return new Intl.PluralRules(tag).select(count);
  } catch {
    return new Intl.PluralRules("en").select(count);
  }
}

function getAiCache(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(I18N_AI_CACHE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return parsed as Record<string, string>;
  } catch {
    return {};
  }
}

function setAiCache(next: Record<string, string>) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(I18N_AI_CACHE_KEY, JSON.stringify(next));
  } catch {
    /* ignore quota */
  }
}

async function requestAiTranslation(locale: Locale, key: string, englishText: string) {
  if (!I18N_AI_ENABLED || !I18N_AI_ENDPOINT) return;
  if (locale === "en") return;
  if (typeof window === "undefined") return;

  const cacheKey = `${locale}:${key}`;
  if (aiRequestedKeys.has(cacheKey)) return;
  aiRequestedKeys.add(cacheKey);

  const cache = getAiCache();
  if (cache[cacheKey]) return;

  try {
    const res = await fetch(I18N_AI_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ locale, key, text: englishText }),
    });
    if (!res.ok) return;
    const data = (await res.json()) as { text?: unknown };
    const translated = typeof data?.text === "string" ? data.text.trim() : "";
    if (!translated) return;

    const nextCache = { ...cache, [cacheKey]: translated };
    setAiCache(nextCache);

    localeOverlays[locale] = { ...(localeOverlays[locale] ?? {}), [key]: translated };
    applyLocale(locale, true);
    emitChange();
  } catch {
    /* ignore */
  }
}

async function fetchLocaleOverlay(locale: Locale): Promise<MessageDict> {
  if (locale === "en") return {};
  try {
    const res = await fetch(`/locales/${locale}.json`, { cache: "no-store" });
    if (!res.ok) {
      if (IS_DEV) {
        console.warn(`[neyra:i18n] locale bundle missing or failed (${res.status}): /locales/${locale}.json — using English base`);
      }
      return {};
    }
    const data = (await res.json()) as unknown;
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      if (IS_DEV) {
        console.warn(`[neyra:i18n] invalid JSON for /locales/${locale}.json — using English base`);
      }
      return {};
    }
    return data as MessageDict;
  } catch {
    if (IS_DEV) {
      console.warn(`[neyra:i18n] network error loading /locales/${locale}.json — using English base`);
    }
    return {};
  }
}

async function ensureLocaleOverlayLoaded(locale: Locale): Promise<void> {
  if (locale === "en") return;
  if (localeFetchDone.has(locale)) return;
  const pending = localeFetchInflight.get(locale);
  if (pending) return pending;

  const task = (async () => {
    try {
      const dict = await fetchLocaleOverlay(locale);
      const cachedAi = typeof window !== "undefined" ? getAiCache() : {};
      const overlay: MessageDict = { ...(dict ?? {}) };
      for (const [k, v] of Object.entries(cachedAi)) {
        if (k.startsWith(`${locale}:`)) overlay[k.slice(locale.length + 1)] = v;
      }
      localeOverlays[locale] = overlay;
    } catch {
      localeOverlays[locale] = {};
    } finally {
      localeFetchDone.add(locale);
      localeFetchInflight.delete(locale);
    }
  })();

  localeFetchInflight.set(locale, task);
  return task;
}

function overlayHasKey(locale: Locale, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(localeOverlays[locale] ?? {}, key);
}

function cleanMessageValue(messages: MessageDict, key: string): string | undefined {
  const v = messages[key];
  if (v === undefined) return undefined;
  if (typeof v === "string" && !v.trim()) return undefined;
  if (looksLikeRawI18nValue(v)) return undefined;
  return v;
}

function translate(state: I18nSnapshot, key: string, vars?: TranslationVars, scope?: string): string {
  if (typeof window !== "undefined" && state.locale !== "en") {
    const cache = getAiCache();
    const cached = cache[`${state.locale}:${key}`];
    if (cached && !looksLikeRawI18nValue(cached)) {
      return encodeI18nMetadata(key, false, interpolateTranslation(cached, vars));
    }
  }

  const countRaw = vars?.count;
  const count = typeof countRaw === "number" ? countRaw : typeof countRaw === "string" ? Number(countRaw) : null;
  if (count != null && Number.isFinite(count)) {
    const category = pluralCategory(state.locale, count);
    const pluralKey = `${key}.${category}`;
    const fallbackPluralKey = `${key}.other`;
    const pluralValue =
      cleanMessageValue(state.messages, pluralKey) ?? cleanMessageValue(state.messages, fallbackPluralKey);
    if (pluralValue) {
      return encodeI18nMetadata(key, false, interpolateTranslation(pluralValue, vars));
    }
  }

  const resolved = cleanMessageValue(state.messages, key);
  if (resolved !== undefined) {
    if (!overlayHasKey(state.locale, key) && state.locale !== "en" && Object.prototype.hasOwnProperty.call(EN_MESSAGES, key)) {
      const enRef = EN_MESSAGES[key];
      if (enRef && !looksLikeRawI18nValue(enRef)) {
        void requestAiTranslation(state.locale, key, String(enRef));
      }
    }
    return encodeI18nMetadata(key, false, interpolateTranslation(resolved, vars));
  }

  warnMissingTranslationWithScope(state.locale, key, scope);

  const enVal = cleanMessageValue(EN_MESSAGES, key);
  const fallbackRaw = enVal !== undefined && enVal !== "" ? enVal : humanizeI18nKey(key);
  return encodeI18nMetadata(key, true, interpolateTranslation(fallbackRaw, vars));
}

export function initializeI18n() {
  if (typeof window === "undefined") return;
  if (localeInitialized) {
    applyDocumentLocale(snapshot.locale);
    return;
  }

  localeInitialized = true;
  const rawStored = localStorage.getItem(STORAGE_KEY);
  const stored = normalizeLocale(rawStored);
  const hadStoredPreference = Boolean(stored);
  if (rawStored && stored && rawStored !== stored) {
    localStorage.setItem(STORAGE_KEY, stored);
  }
  const browser = guessLocaleFromBrowser();

  // New priority order (production-grade):
  // 1) server profile locale (authoritative, but never overwrites manual stored locale on this device)
  // 2) localStorage neyra:locale
  // 3) browser navigator.languages
  // 4) geo/IP (/api/i18n/geo cached to localStorage neyra:geo)
  // 5) fallback en
  //
  // We paint quickly with (stored|browser|cached-geo|en), then refine from profile/geo if allowed.
  if (getToken()) {
    const cachedGeo = (() => {
      try {
        const raw = localStorage.getItem("neyra:geo");
        const obj = raw ? JSON.parse(raw) : null;
        return obj && typeof obj === "object" ? (obj as any) : null;
      } catch {
        return null;
      }
    })();
    const provisional = resolvePreferredLocale({
      storedLocale: rawStored,
      profileLocale: null,
      browserLanguages: (typeof navigator !== "undefined" ? navigator.languages : []) || [],
      geoLocale: cachedGeo?.locale ?? null,
    }).locale;
    applyLocale(provisional, true);
    emitChange();
    void (async () => {
      try {
        const profile = await apiFetch("/profiles/me", { metaReason: "i18n-bootstrap", skipThrottle: true });
        const raw = profile && typeof profile === "object" && "preferred_language" in profile ? (profile as any).preferred_language : null;
        // Never override an explicit stored preference (manual switch).
        if (normalizeLocale(localStorage.getItem(STORAGE_KEY))) {
          const cur = getStoredLocale();
          await ensureLocaleOverlayLoaded(cur);
          applyLocale(cur, true);
          emitChange();
          return;
        }
        const geo = await fetchGeoOnce().catch(() => null);
        const resolved = resolvePreferredLocale({
          storedLocale: null,
          profileLocale: typeof raw === "string" ? raw : null,
          browserLanguages: (typeof navigator !== "undefined" ? navigator.languages : []) || [],
          geoLocale: geo?.locale ?? null,
        }).locale;
        try {
          localStorage.setItem(STORAGE_KEY, resolved);
        } catch {
          /* ignore */
        }
        applyLocale(resolved, true);
        emitChange();
        await ensureLocaleOverlayLoaded(resolved);
        applyLocale(resolved, true);
        emitChange();
      } catch {
        // Even on failure, do not fight stored preference.
        const cur = getStoredLocale();
        await ensureLocaleOverlayLoaded(cur);
        applyLocale(cur, true);
        emitChange();
      }
    })();
    return;
  }

  // Signed out: resolve once using stored|browser|geo|en.
  const cachedGeo = (() => {
    try {
      const raw = localStorage.getItem("neyra:geo");
      const obj = raw ? JSON.parse(raw) : null;
      return obj && typeof obj === "object" ? (obj as any) : null;
    } catch {
      return null;
    }
  })();
  const chosen = resolvePreferredLocale({
    storedLocale: rawStored,
    profileLocale: null,
    browserLanguages: (typeof navigator !== "undefined" ? navigator.languages : []) || [],
    geoLocale: cachedGeo?.locale ?? null,
  }).locale;
  if (!hadStoredPreference) {
    try {
      localStorage.setItem(STORAGE_KEY, chosen);
    } catch {
      /* ignore */
    }
  }
  applyLocale(chosen, true);
  emitChange();

  void (async () => {
    await ensureLocaleOverlayLoaded(chosen);
    applyLocale(chosen, true);
    emitChange();
  })();

  if (!stored && !browser) {
    void guessLocaleFromIp().then((geoLocale) => {
      if (!geoLocale) return;
      if (normalizeLocale(localStorage.getItem(STORAGE_KEY))) return;
      setGlobalLocale(geoLocale);
    });
  }
}

export function setGlobalLocale(next: Locale) {
  if (typeof window !== "undefined") {
    localStorage.setItem(STORAGE_KEY, next);
  }

  // Locale change must never reuse old-language AI suggestions.
  neyraAiLocaleChanged(next);
  neyraAiLocaleClearingSuggestedRepliesCache();
  neyraAiLocaleDevLog("locale changed -> clearing AI suggestions cache", { locale: next });
  clearAiSuggestionCaches();

  applyLocale(next, true);
  emitChange();

  try {
    invalidateApiGetCache("/matches");
    invalidateApiGetCache("/messages/conversations");
    invalidateApiGetCache("/discover/feed");
    invalidateApiGetCache("/nav/badges");
  } catch {
    /* ignore */
  }

  void (async () => {
    await ensureLocaleOverlayLoaded(next);
    applyLocale(next, true);
    emitChange();
  })();

  if (getToken()) {
    void apiFetch("/profiles/me", {
      method: "PATCH",
      body: JSON.stringify({ preferred_language: next }),
      skipThrottle: true,
    })
      .then(() => {
        invalidateApiGetCache("/profiles/me");
      })
      .catch((e: unknown) => {
        console.error("[neyra] failed to persist preferred_language via PATCH /profiles/me", e);
      });
  }
}

export function getStoredLocale(): Locale {
  if (typeof window === "undefined") return snapshot.locale || DEFAULT_LOCALE;
  const stored = normalizeLocale(localStorage.getItem(STORAGE_KEY));
  return stored || snapshot.locale || DEFAULT_LOCALE;
}

/** Same codes the app ships in `LOCALES` — used for AI request bodies and locale-keyed caches. */
export function getCurrentUiLocale(): Locale {
  return getStoredLocale();
}

/** Language code for AI API bodies — always matches the current UI locale (never geo/IP). */
export function getUiLocaleForAiRequests(): Locale {
  return getCurrentUiLocale();
}

/** Canonical locale + human label for AI POST bodies (`locale` + `language_hint`). */
export function getAiLocalePayload(): { locale: Locale; language_hint: string } {
  /** Prefer in-memory i18n snapshot so AI bodies match the UI immediately after `setGlobalLocale`. */
  const locale = (snapshot.locale || getStoredLocale()) as Locale;
  const row = LOCALES.find((l) => l.code === locale);
  const language_hint = row ? `${row.label} (${row.labelEn})` : locale;
  return { locale, language_hint };
}

export function useI18nController() {
  const state = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  useLayoutEffect(() => {
    initializeI18n();
  }, []);

  const setLocale = useCallback((next: Locale) => {
    setGlobalLocale(next);
  }, []);

  const t = useCallback(
    (key: string, vars?: TranslationVars, scope?: string) => translate(state, key, vars, scope),
    [state],
  );

  return useMemo(
    () => ({
      locale: state.locale,
      messages: state.messages,
      ready: state.ready,
      debug: state.debug,
      setLocale,
      t,
    }),
    [state, setLocale, t],
  );
}
