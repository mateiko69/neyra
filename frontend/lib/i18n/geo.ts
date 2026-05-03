import { normalizeLocaleInput } from "./locales";

/** Full geo payload cached for locale + onboarding city prefill (single fetch per browser until cleared). */
export const NEYRA_GEO_STORAGE_KEY = "neyra:geo";

export type NeyraGeoPayload = {
  locale: string | null;
  city: string | null;
  country: string | null;
};

let geoInflight: Promise<NeyraGeoPayload | null> | null = null;

function readCachedGeo(): NeyraGeoPayload | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(NEYRA_GEO_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    const o = parsed as Record<string, unknown>;
    return {
      locale: typeof o.locale === "string" ? o.locale : null,
      city: typeof o.city === "string" ? o.city : null,
      country: typeof o.country === "string" ? o.country : null,
    };
  } catch {
    return null;
  }
}

function cacheHasUsableGeo(c: NeyraGeoPayload | null): boolean {
  if (!c) return false;
  if (c.locale && normalizeLocaleInput(c.locale)) return true;
  return Boolean(c.city?.trim());
}

function writeCachedGeo(payload: NeyraGeoPayload) {
  try {
    localStorage.setItem(NEYRA_GEO_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    /* ignore quota / private mode */
  }
}

/**
 * Geo lookup at most once per app load (concurrent callers share the same promise).
 * Persists to localStorage `neyra:geo`; later calls return cache without hitting the network.
 */
export function fetchGeoOnce(): Promise<NeyraGeoPayload | null> {
  if (typeof window === "undefined") return Promise.resolve(null);

  const cached = readCachedGeo();
  if (cacheHasUsableGeo(cached)) {
    return Promise.resolve(cached);
  }

  if (!geoInflight) {
    geoInflight = (async () => {
      try {
        const res = await fetch("/api/i18n/geo", { method: "GET", cache: "no-store" });
        if (!res.ok) return null;
        const data = (await res.json()) as { locale?: unknown; city?: unknown; country?: unknown };
        const payload: NeyraGeoPayload = {
          locale: typeof data?.locale === "string" ? data.locale : null,
          city: typeof data?.city === "string" ? data.city : null,
          country: typeof data?.country === "string" ? data.country : null,
        };
        if (cacheHasUsableGeo(payload)) {
          writeCachedGeo(payload);
        }
        return payload;
      } catch {
        return null;
      } finally {
        geoInflight = null;
      }
    })();
  }

  return geoInflight;
}
