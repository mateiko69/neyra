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
    .then((result) => ({
      providers: (result ?? null) as SocialProvidersConfig | null,
      failed: false,
    }))
    .catch(() => ({
      providers: null,
      failed: true,
    }));
  return socialProvidersSessionPromise;
}
