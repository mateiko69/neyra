/**
 * Central config for browser-reachable backend URLs.
 *
 * Priority for **API origin** (scheme + host + port, **no** `/api/v1`):
 *   1. NEXT_PUBLIC_API_BASE_URL (preferred name for deployments)
 *   2. NEXT_PUBLIC_BACKEND_URL (legacy / docker-compose)
 *   3. NEXT_PUBLIC_API_URL with `/api/v1` stripped
 *
 * All REST calls use `${origin}/api/v1/...`.
 */

const DEFAULT_BACKEND_ORIGIN = "http://localhost:8000";

function trimEndSlash(s: string): string {
  return s.replace(/\/+$/, "");
}

function normalizeBackendOrigin(raw: string): string {
  let t = trimEndSlash(raw.trim());
  t = t.replace(/\/api\/v1$/i, "");
  return t;
}

/** Origin only: scheme + host + port. No trailing slash. */
export function getBackendPublicOrigin(): string {
  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (apiBase) return normalizeBackendOrigin(apiBase);

  const fromEnv = process.env.NEXT_PUBLIC_BACKEND_URL?.trim();
  if (fromEnv) return normalizeBackendOrigin(fromEnv);

  const legacyApi = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (legacyApi) return normalizeBackendOrigin(legacyApi);

  return DEFAULT_BACKEND_ORIGIN;
}

/** REST base: .../api/v1 (no trailing slash). */
export function getApiV1BaseUrl(): string {
  return `${getBackendPublicOrigin()}/api/v1`;
}

export const BACKEND_PUBLIC_URL = getBackendPublicOrigin();
export const API_URL = getApiV1BaseUrl();
