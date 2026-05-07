/**
 * Process-wide UI locale for outbound API requests.
 * Mirrors i18n snapshot (not stale localStorage) — updated from `applyLocale` / `setGlobalLocale`.
 */
let _liveLocaleForApi = "en";

/** Called from i18n when the UI locale changes. */
export function setAppLocaleForApi(locale: string): void {
  const next = String(locale || "en").trim() || "en";
  _liveLocaleForApi = next;
}

/** Locale for `X-App-Locale`, `Accept-Language`, and AI POST bodies — always matches active UI. */
export function getCurrentLocaleForApi(): string {
  return _liveLocaleForApi;
}
