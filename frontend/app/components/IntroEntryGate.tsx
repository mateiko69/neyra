"use client";

import type { ReactNode } from "react";
import { useLayoutEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { isIntroSeen } from "../../lib/introSeen";

/**
 * First visit to auth: redirect to /intro. Does not block returning users after intro_seen is set.
 */
export function IntroEntryGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [showAuth, setShowAuth] = useState(false);

  useLayoutEffect(() => {
    if (isIntroSeen()) {
      setShowAuth(true);
      return;
    }
    router.replace("/intro");
  }, [router]);

  if (!showAuth) {
    return <div className="intro-entry-gate" aria-busy="true" aria-live="polite" />;
  }

  return <>{children}</>;
}
