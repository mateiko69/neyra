"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { captureReferralCodeFromLocation } from "../../lib/referralCapture";

export function ReferralCapture() {
  const pathname = usePathname();
  useEffect(() => {
    captureReferralCodeFromLocation();
  }, [pathname]);
  return null;
}
