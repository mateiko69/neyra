/** Routes that use PublicMarketingShell styling and must not show in-app bottom/tab navigation. */
const PUBLIC_MARKETING_EXACT = new Set(["/", "/premium", "/privacy", "/terms", "/refund", "/contact"]);

export function normalizePath(pathname: string): string {
  return pathname.split("?")[0] || "/";
}

export function isPublicMarketingRoute(pathname: string): boolean {
  return PUBLIC_MARKETING_EXACT.has(normalizePath(pathname));
}
