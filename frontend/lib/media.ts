/**
 * Single place for profile / upload image URLs.
 * Works with absolute http(s) URLs (seed, CDN) and relative /uploads/... paths.
 */

import { BACKEND_PUBLIC_URL } from "./apiBase";

const PLACEHOLDER_SVG = encodeURIComponent(
  `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="1000" viewBox="0 0 800 1000">
    <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#6f5cff"/><stop offset="55%" stop-color="#2b1c66"/><stop offset="100%" stop-color="#131827"/>
    </linearGradient></defs>
    <rect width="800" height="1000" fill="url(#g)"/>
    <circle cx="650" cy="166" r="72" fill="rgba(255,208,92,0.92)"/>
    <path d="M650 108l16 34 36 5-26 26 7 36-33-18-33 18 7-36-26-26 36-5z" fill="rgba(95,66,6,0.8)"/>
    <circle cx="400" cy="382" r="86" fill="rgba(255,255,255,0.22)"/>
    <path d="M240 776c44-110 132-166 160-166s116 56 160 166" fill="none" stroke="rgba(255,255,255,0.22)" stroke-width="48" stroke-linecap="round"/>
    <text x="400" y="924" text-anchor="middle" font-family="Inter,Arial,sans-serif" font-size="30" font-weight="700" fill="rgba(255,255,255,0.86)">NEYRA PREMIUM</text>
  </svg>`,
);

/** Shown when src is missing or fails to load (no broken-image icon). */
export const PRIMARY_IMAGE_PLACEHOLDER = `data:image/svg+xml,${PLACEHOLDER_SVG}`;

/** Public API origin (serves /uploads static files). Browser must be able to reach this host. */
export function getBackendPublicUrl(): string {
  return BACKEND_PUBLIC_URL;
}

function shouldRewriteMediaHost(hostname: string): boolean {
  const h = String(hostname || "").toLowerCase();
  if (!h) return false;
  if (h === "localhost" || h === "127.0.0.1" || h === "0.0.0.0") return true;
  if (h === "backend" || h === "api" || h === "host.docker.internal") return true;
  if (h.endsWith(".docker.internal") || h.endsWith(".local")) return true;
  if (/^10\./.test(h) || /^192\.168\./.test(h) || /^172\.(1[6-9]|2\d|3[01])\./.test(h)) return true;
  return false;
}

/** Resolve a single stored URL for use in <img src>. */
export function resolveMediaUrl(url: string): string {
  if (!url) return "";
  const u = url.trim();
  if (!u) return "";
  // Bundled demo catalog assets MUST always resolve from the frontend origin (never API).
  // Important: this function is used during server-render of client components too (window undefined).
  if (u.startsWith("/demo-profiles/") || u.startsWith("demo-profiles/")) {
    return u.startsWith("/") ? u : `/${u}`;
  }
  if (typeof window !== "undefined") {
    const origin = window.location.origin.replace(/\/+$/, "");
    const absPrefix = `${origin}/`;
    if (u.startsWith(absPrefix)) {
      const pathOnly = u.slice(origin.length);
      /** Bundled demo catalog photos are served from Next `public/demo-profiles` (same origin). */
      if (pathOnly.startsWith("/demo-profiles/")) {
        return pathOnly;
      }
      if (pathOnly.startsWith("/uploads/")) {
        return `${getBackendPublicUrl().replace(/\/+$/, "")}${pathOnly}`;
      }
    }
  }
  if (u.startsWith("data:") || u.startsWith("blob:")) return u;
  if (u.startsWith("http://") || u.startsWith("https://")) {
    try {
      const parsed = new URL(u);
      const path = `${parsed.pathname}${parsed.search || ""}`;
      const publicBase = getBackendPublicUrl().replace(/\/+$/, "");
      const publicOrigin = new URL(publicBase).origin;
      /** Demo bundle paths should render from the web origin (Vercel static), not the API host. */
      if (parsed.pathname.startsWith("/demo-profiles/")) {
        return path;
      }
      const isAppPath = path.startsWith("/uploads/") || path.startsWith("/demo-profiles/");
      if (isAppPath && shouldRewriteMediaHost(parsed.hostname) && parsed.origin !== publicOrigin) {
        return `${publicBase}${path}`;
      }
    } catch {
      /* keep absolute URL as-is */
    }
    return u;
  }
  if (u.startsWith("//")) {
    if (typeof window !== "undefined" && window.location?.protocol) {
      return `${window.location.protocol}${u}`;
    }
    return `https:${u}`;
  }
  const path = u.startsWith("/") ? u : `/${u}`;
  if (path.startsWith("/demo-profiles/")) {
    return path;
  }
  return `${getBackendPublicUrl()}${path}`;
}

/** Normalize API photo list (array or comma-separated string). */
export function photosFromList(urls: string[] | string | undefined | null): string[] {
  if (urls == null) return [];
  const list = Array.isArray(urls)
    ? urls
    : String(urls)
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean);
  return list.map((x) => (x || "").trim()).filter(Boolean);
}

/** First non-empty photo in a list (Discover / matches primary). Accepts API array or comma-separated string. */
export function primaryPhotoFromList(urls: string[] | string | undefined | null): string {
  const list = photosFromList(urls);
  return list[0] || "";
}
