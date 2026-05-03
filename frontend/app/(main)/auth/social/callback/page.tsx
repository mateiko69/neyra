"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiFetch, clearAuth, setAccessToken } from "../../../../../lib/api";
import { trackAnalyticsEvent } from "../../../../../lib/analytics";
import { isPendingPostSignupReferral, promoteSignupFlowToPendingReferralModal } from "../../../../../lib/referralSignupFlow";
import { useT } from "../../../../components/i18n/I18nProvider";

function parseHash(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const raw = window.location.hash?.replace(/^#/, "") || "";
  const params = new URLSearchParams(raw);
  const out: Record<string, string> = {};
  for (const [k, v] of params.entries()) out[k] = v;
  return out;
}

function safePath(raw: string | undefined): string {
  const v = (raw || "").trim();
  if (!v.startsWith("/")) return "/discover";
  if (v.startsWith("//")) return "/discover";
  return v;
}

function profileLooksIncomplete(profile: any): boolean {
  if (!profile || typeof profile !== "object") return true;
  const displayName = String(profile.display_name || "").trim();
  const photoCsv = String(profile.photo_urls || "").trim();
  const photos = photoCsv.split(",").map((p: string) => p.trim()).filter(Boolean);
  const gender = String(profile.gender || "").trim();
  const interestedIn = String(profile.interested_in || "").trim();
  const minAge = profile.min_preferred_age;
  const maxAge = profile.max_preferred_age;

  if (!displayName) return true;
  if (photos.length === 0) return true;
  if (!gender) return true;
  if (!interestedIn) return true;
  if (typeof minAge !== "number" || typeof maxAge !== "number") return true;
  if (minAge < 18 || maxAge > 99 || minAge > maxAge) return true;

  // Optional fields (location, relationship goals, etc.) may exist,
  // but we don't hard-require them here to avoid blocking users incorrectly.
  return false;
}

export default function SocialCallbackPage() {
  const router = useRouter();
  const { t } = useT("SocialCallbackPage");
  const [status, setStatus] = useState<"loading" | "failed">("loading");

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const params = parseHash();
      const token = (params.access_token || "").trim();
      const suggestedRedirect = safePath(params.redirect_path);
      if (!token) {
        setStatus("failed");
        return;
      }

      // Save token first so the following "me" calls authenticate.
      setAccessToken(token);
      promoteSignupFlowToPendingReferralModal();
      if (isPendingPostSignupReferral()) {
        void trackAnalyticsEvent("signup_completed", { source: "oauth" });
      }

      try {
        // Prefer /auth/me because it includes backend "onboarding_required".
        const authMe = await apiFetch("/auth/me", { method: "GET", skipAuthRedirect: true });
        if (cancelled) return;

        if (Boolean(authMe && typeof authMe === "object" ? (authMe as any).is_deleted : false)) {
          router.replace("/account/restore");
          return;
        }

        const onboardingRequired = Boolean(authMe?.onboarding_required);
        if (onboardingRequired) {
          router.replace("/onboarding");
          return;
        }

        // If backend says onboarding not required, still sanity-check profile.
        // This avoids edge cases where profile row exists but missing required fields.
        const profile = await apiFetch("/profiles/me", { method: "GET", skipAuthRedirect: true });
        if (cancelled) return;
        if (profileLooksIncomplete(profile)) {
          router.replace("/onboarding");
          return;
        }

        router.replace(suggestedRedirect || "/discover");
      } catch (error) {
        // Clear broken token to avoid 401 loops.
        clearAuth();
        if (cancelled) return;
        setStatus("failed");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [router]);

  if (status === "loading") {
    return (
      <div style={{ padding: 24, maxWidth: 520, margin: "0 auto" }}>
        <h1 style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>{t("auth.social.callback.signingIn")}</h1>
        <p style={{ opacity: 0.8 }}>{t("auth.social.callback.settingUp")}</p>
      </div>
    );
  }

  return (
    <div style={{ padding: 24, maxWidth: 520, margin: "0 auto" }}>
      <h1 style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>{t("auth.social.callback.failedTitle")}</h1>
      <p style={{ opacity: 0.8, marginBottom: 12 }}>{t("auth.social.callback.failedSubtitle")}</p>
      <Link href="/login">{t("auth.social.callback.backToLogin")}</Link>
    </div>
  );
}

