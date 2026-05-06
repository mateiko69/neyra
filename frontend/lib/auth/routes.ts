/** App routes that never require a session for first paint / redirect targets. */
const PUBLIC_EXACT = new Set(["/", "/premium", "/privacy", "/terms", "/refunds", "/refund", "/contact"]);

const PUBLIC_PREFIXES = [
  "/intro",
  "/login",
  "/signup",
  "/auth/social/callback",
  "/account/restore",
  "/verify-email",
] as const;

export function normalizeAppPath(pathname: string): string {
  return pathname.split("?")[0] || "/";
}

export function isPublicAppPath(pathname: string): boolean {
  const p = normalizeAppPath(pathname);
  if (PUBLIC_EXACT.has(p)) return true;
  for (const prefix of PUBLIC_PREFIXES) {
    if (p === prefix || p.startsWith(`${prefix}/`)) return true;
  }
  return false;
}
