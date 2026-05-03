/**
 * Native share / clipboard fallback for viral moments (match, top profile, invite).
 */

/** Pre-filled copy for “share NEYRA” from AI opener quick actions. */
export const NEYRA_OPENER_VIRAL_SHARE_TEXT =
  "😂 This app writes better openers than me.\nTry it: https://neyra.app";

export const NEYRA_APP_SHARE_URL = "https://neyra.app";

/** Append attribution for viral image / friend trials (`signup_from_share` analytics). */
export function withViralShareAttribution(url: string): string {
  const u = (url || "").trim() || `${NEYRA_APP_SHARE_URL}/signup`;
  if (/\bsrc=viral\b/i.test(u) || u.includes("src%3Dviral")) return u;
  return u.includes("?") ? `${u}&src=viral` : `${u}?src=viral`;
}

export function openerShareTelegramUrl(text: string = NEYRA_OPENER_VIRAL_SHARE_TEXT): string {
  return `https://t.me/share/url?text=${encodeURIComponent(text)}`;
}

export function openerShareWhatsAppUrl(text: string = NEYRA_OPENER_VIRAL_SHARE_TEXT): string {
  return `https://api.whatsapp.com/send?text=${encodeURIComponent(text)}`;
}

export async function shareOrCopy(opts: { title: string; text: string; url: string; analyticsName?: string }): Promise<boolean> {
  const { title, text, url, analyticsName } = opts;
  try {
    const nav = globalThis.navigator;
    if (nav && "share" in nav && typeof nav.share === "function") {
      await nav.share({ title, text, url });
      if (analyticsName && typeof process !== "undefined") {
        const { trackAnalyticsEvent } = await import("./analytics");
        void trackAnalyticsEvent(analyticsName, { channel: "native_share", url });
      }
      return true;
    }
  } catch {
    /* user cancelled or share unsupported */
  }
  try {
    await navigator.clipboard.writeText(url);
    if (analyticsName) {
      const { trackAnalyticsEvent } = await import("./analytics");
      void trackAnalyticsEvent(analyticsName, { channel: "clipboard", url });
    }
    return true;
  } catch {
    return false;
  }
}
