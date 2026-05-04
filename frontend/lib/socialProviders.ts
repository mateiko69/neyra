import { apiFetch } from "./api";

export type SocialProvidersConfig = {
  google: boolean;
  apple: boolean;
  facebook: boolean;
  google_client_id: string;
  apple_client_id: string;
  facebook_app_id: string;
  dev_mock?: boolean;
  providers?: {
    google?: { provider: "google"; enabled: boolean; missing_config_keys: string[] };
    apple?: { provider: "apple"; enabled: boolean; missing_config_keys: string[] };
    facebook?: { provider: "facebook"; enabled: boolean; missing_config_keys: string[] };
  };
};

export type SocialProvidersState = {
  providers: SocialProvidersConfig | null;
  failed: boolean;
};

function truthyEnvFlag(v: unknown): boolean {
  if (v === true || v === 1) return true;
  if (typeof v === "string") return v.trim().toLowerCase() === "true" || v.trim() === "1";
  return false;
}

/** Backend may omit `enabled` when listing providers; treat presence as available unless explicitly disabled. */
function recordImpliesGoogleEnabled(rec: Record<string, unknown>): boolean {
  if (truthyEnvFlag(rec.disabled)) return false;
  if ("enabled" in rec) return truthyEnvFlag(rec.enabled);
  return true;
}

/**
 * Normalize `/auth/social/providers` JSON so Google availability matches backend variants:
 * top-level `google`, nested `providers.google.enabled`, alternate keys (`Google`, `google_oauth`),
 * or array-shaped provider lists.
 */
export function normalizeSocialProvidersPayload(raw: unknown): SocialProvidersConfig | null {
  if (raw == null || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;

  let nestedGoogleObj: Record<string, unknown> | undefined;
  const nested = o.providers;

  if (Array.isArray(nested)) {
    for (const item of nested) {
      if (!item || typeof item !== "object") continue;
      const rec = item as Record<string, unknown>;
      const pid = String(rec.provider ?? rec.id ?? rec.name ?? "").trim().toLowerCase();
      if (pid === "google" || pid === "google_oauth") {
        nestedGoogleObj = rec;
        break;
      }
    }
  } else if (nested && typeof nested === "object") {
    const n = nested as Record<string, unknown>;
    const g = n.google ?? n.Google ?? n.google_oauth;
    if (g && typeof g === "object" && !Array.isArray(g)) {
      nestedGoogleObj = g as Record<string, unknown>;
    } else if (g === true) {
      nestedGoogleObj = { enabled: true };
    }
  }

  const topGoogle =
    truthyEnvFlag(o.google) || truthyEnvFlag(o.Google) || truthyEnvFlag(o.google_oauth);
  const nestedEnabled = nestedGoogleObj ? recordImpliesGoogleEnabled(nestedGoogleObj) : false;

  const google = topGoogle || nestedEnabled;

  const clientFromNested =
    typeof nestedGoogleObj?.client_id === "string"
      ? nestedGoogleObj.client_id.trim()
      : typeof nestedGoogleObj?.clientId === "string"
        ? (nestedGoogleObj.clientId as string).trim()
        : "";

  const google_client_id =
    (typeof o.google_client_id === "string" && o.google_client_id.trim() !== ""
      ? o.google_client_id.trim()
      : typeof o.GOOGLE_CLIENT_ID === "string" && o.GOOGLE_CLIENT_ID.trim() !== ""
        ? o.GOOGLE_CLIENT_ID.trim()
        : clientFromNested) || "";

  const structuredProviders =
    nested && typeof nested === "object" && !Array.isArray(nested)
      ? (nested as SocialProvidersConfig["providers"])
      : undefined;

  return {
    google,
    apple: Boolean(o.apple),
    facebook: Boolean(o.facebook),
    google_client_id,
    apple_client_id: typeof o.apple_client_id === "string" ? o.apple_client_id : "",
    facebook_app_id: typeof o.facebook_app_id === "string" ? o.facebook_app_id : "",
    dev_mock: Boolean(o.dev_mock),
    providers: structuredProviders,
  };
}

/** True when Google OAuth should be offered (redirect flow does not require `google_client_id` in the browser). */
export function isGoogleLoginAvailable(cfg: SocialProvidersConfig | null): boolean {
  if (!cfg) return false;
  if (cfg.google) return true;
  if (cfg.providers?.google?.enabled) return true;
  if (typeof cfg.google_client_id === "string" && cfg.google_client_id.trim() !== "") return true;
  return false;
}

function devLogSocialProviders(message: string, details: Record<string, unknown>) {
  if (process.env.NODE_ENV !== "development") return;
  if (typeof window === "undefined") return;
  console.debug(`[neyra] ${message}`, details);
}

/**
 * One GET /auth/social/providers for the life of the page (until full reload).
 * Strict Mode and remounts share the same promise, and failures stay non-throwing
 * so email/password auth remains available.
 */
let socialProvidersSessionPromise: Promise<SocialProvidersState> | null = null;

export function loadSocialProviders(): Promise<SocialProvidersState> {
  if (socialProvidersSessionPromise) return socialProvidersSessionPromise;
  socialProvidersSessionPromise = apiFetch("/auth/social/providers", {
    skipAuthRedirect: true,
    metaReason: "social-providers-once",
  })
    .then((result) => {
      const normalized = normalizeSocialProvidersPayload(result);
      const available = isGoogleLoginAvailable(normalized);
      devLogSocialProviders("social providers resolved", {
        googleAvailable: available,
        topLevelGoogle: normalized?.google,
        nestedGoogleEnabled: normalized?.providers?.google?.enabled,
        hasGoogleClientId: Boolean(normalized?.google_client_id?.trim()),
        responseKeys:
          result && typeof result === "object" && !Array.isArray(result)
            ? Object.keys(result as object)
            : [],
      });
      return {
        providers: normalized,
        failed: false,
      };
    })
    .catch(() => ({
      providers: null,
      failed: true,
    }));
  return socialProvidersSessionPromise;
}
