"use client";

import { useContext, useEffect, useRef, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { getAuthMeSnapshot } from "../../lib/auth/bootstrap";
import { AUTH_EXPIRED_EVENT, authSafeReplace, resetAuthRedirectLock } from "../../lib/auth/navigation";
import { isPublicAppPath, normalizeAppPath } from "../../lib/auth/routes";
import { getAuthState } from "../../lib/api";
import { AuthBootContext } from "./AuthBootstrapGate";

export function AuthRouteGuard({ children }: { children: ReactNode }) {
  const pathname = usePathname() || "/";
  const router = useRouter();
  const boot = useContext(AuthBootContext);
  const phase = boot?.phase ?? "ready";
  const pathnameRef = useRef(pathname);
  pathnameRef.current = pathname;
  const p = normalizeAppPath(pathname);
  const isPublic = isPublicAppPath(p);

  useEffect(() => {
    resetAuthRedirectLock();
  }, [pathname]);

  useEffect(() => {
    const onExpired = () => {
      const cur = normalizeAppPath(pathnameRef.current);
      if (isPublicAppPath(cur)) return;
      authSafeReplace(router, cur, "/login");
    };
    if (typeof window === "undefined") return;
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
  }, [router]);

  useEffect(() => {
    if (phase !== "ready") return;
    const cur = normalizeAppPath(pathname);
    const publicHere = isPublicAppPath(cur);
    const authed = getAuthState() === "authorized";
    const snap = getAuthMeSnapshot();
    const needsOnboarding = Boolean(snap?.onboarding_required && !snap?.onboarding_completed);

    if (!authed) {
      if (!publicHere) {
        authSafeReplace(router, cur, "/login");
      }
      return;
    }

    if (needsOnboarding) {
      if (!publicHere && !cur.startsWith("/onboarding")) {
        authSafeReplace(router, cur, "/onboarding");
      }
      return;
    }

    if (cur.startsWith("/onboarding")) {
      authSafeReplace(router, cur, "/discover");
    }
  }, [phase, pathname, router]);

  // API unreachable: never block or show session/API banners — render UI (public + authed).
  if (phase === "network") {
    return <>{children}</>;
  }

  if (phase === "loading" && !isPublic) {
    return <div className="auth-boot-loading" aria-busy="true" aria-live="polite" style={{ minHeight: "42vh" }} />;
  }

  return <>{children}</>;
}
