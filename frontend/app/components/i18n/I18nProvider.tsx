"use client";

import type { ReactNode } from "react";
import { Fragment, createContext, useCallback, useContext, useEffect } from "react";
import type { Locale } from "../../../lib/i18n";
import { isLocaleRtl, normalizeLocaleInput, useI18nController } from "../../../lib/i18n";
import { HTML_LANG_BY_APP } from "../../../lib/i18n/locales";
import { AppShellSkeleton } from "../AppShellSkeleton";
import { I18nDebugRuntime } from "./I18nDebugRuntime";

type I18nContextValue = {
  locale: Locale;
  setLocale: (next: Locale) => void | Promise<void>;
  debug: boolean;
  translate: (key: string, vars?: Record<string, string | number>, scope?: string) => string;
};

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const { locale, ready, setLocale, t, debug } = useI18nController();
  // Align client state + DOM with localStorage and `<html lang>` without full reloads (reloads caused
  // RSC / layout to reset `lang` and loop with Next dev fast-refresh).
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const rawStored = String(localStorage.getItem("neyra:locale") || "").trim();
      const normalizedStored = normalizeLocaleInput(rawStored);
      if (normalizedStored && normalizedStored !== locale) {
        void Promise.resolve(setLocale(normalizedStored));
      }
    } catch {
      /* ignore */
    }
    try {
      const expectedLang = (HTML_LANG_BY_APP as Record<string, string>)[locale] ?? locale;
      const currentLang = document.documentElement.lang || "";
      if (expectedLang && currentLang !== expectedLang) {
        document.documentElement.lang = expectedLang;
        document.documentElement.dir = isLocaleRtl(locale) ? "rtl" : "ltr";
      }
    } catch {
      /* ignore */
    }
  }, [locale, setLocale]);

  if (!ready) {
    return <AppShellSkeleton />;
  }
  const dir = isLocaleRtl(locale) ? "rtl" : "ltr";

  return (
    <I18nContext.Provider value={{ locale, setLocale, debug, translate: t }}>
      {debug ? <I18nDebugRuntime /> : null}
      {/* Remount UI on locale change so no component keeps stale non-t() strings in memory. */}
      <div className="neyra-i18n-root" data-testid="neyra-i18n-root" data-dir={dir} style={{ display: "contents" }}>
        <Fragment key={locale}>{children}</Fragment>
      </div>
    </I18nContext.Provider>
  );
}

export function useT(scope?: string) {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    return {
      locale: "en" as const,
      setLocale: async () => {},
      debug: false,
      t: () => "",
    };
  }
  const { locale, setLocale, debug, translate } = ctx;
  const t = useCallback(
    (key: string, vars?: Record<string, string | number>) => translate(key, vars, scope),
    [translate, scope, locale],
  );
  return {
    locale,
    setLocale,
    debug,
    t,
  };
}
