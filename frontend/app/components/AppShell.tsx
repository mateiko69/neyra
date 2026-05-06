"use client";

import type { ReactNode } from "react";
import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { AppNavigation } from "./AppNavigation";
import { LanguageSwitcher } from "./i18n/LanguageSwitcher";
import { DevClickAudit } from "./DevClickAudit";
import { ReferralCapture } from "./ReferralCapture";
import { ReferralClaimOnBoot } from "./ReferralClaimOnBoot";
import { PostSignupReferralModal } from "./PostSignupReferralModal";
import { DailyBoostsBanner } from "./DailyBoostsBanner";
import { GrowthEngagementLayer } from "./growth/GrowthEngagementLayer";
import { isPublicMarketingRoute } from "../../lib/public-marketing-paths";

export function AppShell({ children }: { children: ReactNode }) {
  useEffect(() => {
    const onUnhandledRejection = (event: PromiseRejectionEvent) => {
      console.warn("unhandled promise rejection captured", { reason: event.reason });
    };
    window.addEventListener("unhandledrejection", onUnhandledRejection);
    return () => window.removeEventListener("unhandledrejection", onUnhandledRejection);
  }, []);

  const pathname = usePathname() || "/";
  const isOnboarding = pathname.startsWith("/onboarding");
  const isIntro = pathname.startsWith("/intro");
  const isPublicMarketing = isPublicMarketingRoute(pathname);

  if (isPublicMarketing) {
    return (
      <>
        <DevClickAudit />
        {children}
      </>
    );
  }

  return (
    <>
      {isOnboarding ? (
        <div className="onboarding-lang-bar">
          <LanguageSwitcher />
        </div>
      ) : null}
      {isOnboarding || isIntro ? null : <ReferralCapture />}
      {isOnboarding || isIntro ? null : <ReferralClaimOnBoot />}
      {isOnboarding || isIntro ? null : <PostSignupReferralModal />}
      <DevClickAudit />
      {isOnboarding || isIntro ? null : <AppNavigation />}
      <div className={`shell-main${isIntro ? " shell-main--intro" : ""}`}>
      {isOnboarding || isIntro ? null : <DailyBoostsBanner />}
      {isOnboarding || isIntro ? null : <GrowthEngagementLayer />}
      <div className="page-canvas">{children}</div>
      </div>
    </>
  );
}
