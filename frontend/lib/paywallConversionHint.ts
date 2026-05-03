import { trackAnalyticsEvent } from "./analytics";

const STORAGE_KEY = "neyra_paywall_conversion_hint";

export type PaywallConversionHint = "after_reply" | "after_match";

export function setPaywallConversionHint(hint: PaywallConversionHint): void {
  try {
    if (typeof sessionStorage === "undefined") return;
    sessionStorage.setItem(STORAGE_KEY, hint);
  } catch {
    /* ignore */
  }
}

/** Clears and returns the hint so purchase attribution fires at most once per stored hint. */
export function consumePaywallConversionHint(): PaywallConversionHint | null {
  try {
    if (typeof sessionStorage === "undefined") return null;
    const raw = sessionStorage.getItem(STORAGE_KEY);
    sessionStorage.removeItem(STORAGE_KEY);
    if (raw === "after_reply" || raw === "after_match") return raw;
    return null;
  } catch {
    return null;
  }
}

/** Call after a successful upgrade / checkout when `premium_purchased` (or equivalent) is emitted. */
export function emitConversionAfterPurchase(): void {
  const hint = consumePaywallConversionHint();
  if (hint === "after_reply") {
    void trackAnalyticsEvent("conversion_after_reply", { channel: "purchase" });
  } else if (hint === "after_match") {
    void trackAnalyticsEvent("conversion_after_match", { channel: "purchase" });
  }
}
