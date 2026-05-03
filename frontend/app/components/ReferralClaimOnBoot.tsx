"use client";

import { useEffect } from "react";
import { tryConsumePendingReferralClaim } from "../../lib/referralClaim";

/** Claim pending ?ref= after session is available (refresh, deep link). */
export function ReferralClaimOnBoot() {
  useEffect(() => {
    const t = window.setTimeout(() => void tryConsumePendingReferralClaim(), 1200);
    return () => window.clearTimeout(t);
  }, []);
  return null;
}
