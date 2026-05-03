"use client";

import { useCallback, useState } from "react";
import { NEYRA_PREMIUM_PRICE_ID, openCheckout } from "../../lib/paddle";

export function BuyPremiumButton() {
  const [busy, setBusy] = useState(false);

  const onClick = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    try {
      await openCheckout(NEYRA_PREMIUM_PRICE_ID, 1);
    } finally {
      setBusy(false);
    }
  }, [busy]);

  return (
    <button
      type="button"
      disabled={busy}
      onClick={() => void onClick()}
      aria-busy={busy}
      style={{
        border: "none",
        borderRadius: 14,
        padding: "14px 28px",
        fontSize: 16,
        fontWeight: 700,
        letterSpacing: "0.02em",
        cursor: busy ? "wait" : "pointer",
        color: "#fafafa",
        background: "linear-gradient(135deg, #6d28d9 0%, #9333ea 42%, #a855f7 100%)",
        boxShadow: "0 6px 20px rgba(109, 40, 217, 0.45)",
        opacity: busy ? 0.85 : 1,
        transition: "opacity 0.15s ease, transform 0.15s ease",
      }}
      onMouseDown={(e) => {
        if (!busy) (e.currentTarget as HTMLButtonElement).style.transform = "scale(0.98)";
      }}
      onMouseUp={(e) => {
        (e.currentTarget as HTMLButtonElement).style.transform = "scale(1)";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLButtonElement).style.transform = "scale(1)";
      }}
    >
      🔥 Get Premium
    </button>
  );
}
