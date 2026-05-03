/**
 * Central config for browser-reachable backend URLs.
 *
 * - NEXT_PUBLIC_BACKEND_URL — origin only, e.g. http://localhost:8000 (no /api/v1).
 *   All REST calls use `${BACKEND}/api/v1/...`. Set this in .env.local to match the host
 *   port where Docker publishes the API (see docker-compose ports).
 *
 * - NEXT_PUBLIC_API_URL — optional legacy override for the full API base including /api/v1.
 *   If NEXT_PUBLIC_BACKEND_URL is set, it wins for deriving API_URL.
 */

const DEFAULT_BACKEND_ORIGIN = "http://localhost:8000";

function trimEndSlash(s: string): string {
  return s.replace(/\/+$/, "");
}

/** Origin only: scheme + host + port. No trailing slash. */
export function getBackendPublicOrigin(): string {
  const fromEnv = process.env.NEXT_PUBLIC_BACKEND_URL?.trim();
  if (fromEnv) return trimEndSlash(fromEnv);

  const legacyApi = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (legacyApi) {
    const base = trimEndSlash(legacyApi).replace(/\/api\/v1$/i, "");
    if (base) return base;
  }

  return DEFAULT_BACKEND_ORIGIN;
}

/** REST base: .../api/v1 (no trailing slash). */
export function getApiV1BaseUrl(): string {
  const fromEnv = process.env.NEXT_PUBLIC_BACKEND_URL?.trim();
  if (fromEnv) return `${trimEndSlash(fromEnv)}/api/v1`;

  const legacy = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (legacy) return trimEndSlash(legacy);

  return `${DEFAULT_BACKEND_ORIGIN}/api/v1`;
}

export const BACKEND_PUBLIC_URL = getBackendPublicOrigin();
export const API_URL = getApiV1BaseUrl();
