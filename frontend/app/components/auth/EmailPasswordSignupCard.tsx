"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { apiFetch, applyAuthBootstrapResult, setAccessToken } from "../../../lib/api";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { getAuthBootstrapResult, primeAuthBootstrapFromMe } from "../../../lib/auth/bootstrap";
import { apiFailureToI18nText } from "../../../lib/i18n/translateApiUserMessage";
import { i18nKey, type I18nText } from "../../../lib/i18n/message";
import { useT } from "../i18n/I18nProvider";
import { Button, Input } from "../ui";

function safeRedirect(raw: string | null): "/onboarding" | "/discover" {
  const v = (raw || "").trim();
  if (v === "/onboarding" || v === "/discover") return v;
  return "/discover";
}

export function EmailPasswordSignupCard(props: { onError: (msg: I18nText) => void }) {
  const { t } = useT("SignupPage");
  const router = useRouter();
  const searchParams = useSearchParams();
  const referralDefault = useMemo(() => (searchParams.get("ref") || "").trim().slice(0, 32) || "", [searchParams]);
  const viralAttribution = useMemo(() => (searchParams.get("src") || "").trim().toLowerCase(), [searchParams]);

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const afterSignup = useCallback(
    async (accessToken: string) => {
      setAccessToken(accessToken);
      const me = await apiFetch("/auth/me", { method: "GET", metaReason: "signup-email-after-register", skipThrottle: true });
      primeAuthBootstrapFromMe(me);
      await getAuthBootstrapResult({ force: true }).then(applyAuthBootstrapResult);
      if (me && typeof me === "object" && Boolean((me as any).is_deleted)) {
        router.replace("/account/restore");
        return;
      }
      const onboardingRequired = Boolean(me && typeof me === "object" ? (me as any).onboarding_required : false);
      const nextPath = onboardingRequired ? "/onboarding" : safeRedirect(searchParams.get("next"));
      router.replace(nextPath);
    },
    [router, searchParams],
  );

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const name = displayName.trim();
    const em = email.trim();
    const pw = password;
    if (!name) {
      props.onError(i18nKey("auth.signup.errors.nameRequired"));
      return;
    }
    if (!em) {
      props.onError(i18nKey("auth.signup.errors.emailRequired"));
      return;
    }
    if (!pw.trim()) {
      props.onError(i18nKey("auth.signup.errors.passwordRequired"));
      return;
    }
    if (pw.length < 8) {
      props.onError(i18nKey("auth.signup.errors.passwordShort"));
      return;
    }
    if (busy) return;
    setBusy(true);
    try {
      const body: Record<string, unknown> = {
        email: em,
        password: pw,
        display_name: name,
      };
      if (referralDefault) body.referral_code = referralDefault;
      const res = (await apiFetch("/auth/register", {
        method: "POST",
        metaReason: "signup-email-register",
        body: JSON.stringify(body),
        skipThrottle: true,
      })) as { access_token?: string };
      const tok = typeof res?.access_token === "string" ? res.access_token.trim() : "";
      if (!tok) {
        props.onError(i18nKey("auth.signup.errors.noToken"));
        return;
      }
      void trackAnalyticsEvent("signup_completed", { source: "email" });
      if (referralDefault && viralAttribution === "viral") {
        void trackAnalyticsEvent("signup_from_share", { source: "email", referral_code: referralDefault });
      }
      await afterSignup(tok);
    } catch (err) {
      props.onError(apiFailureToI18nText(err, t, "auth.signup.errors.failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="auth-email-form" onSubmit={(e) => void onSubmit(e)} style={{ display: "grid", gap: 12 }}>
      <div className="caption" style={{ opacity: 0.85, textAlign: "center" }}>
        {t("auth.signup.dividerEmail")}
      </div>
      <Input
        name="display_name"
        autoComplete="name"
        value={displayName}
        onChange={(e) => setDisplayName(e.target.value)}
        placeholder={t("auth.signup.displayNamePlaceholder")}
        disabled={busy}
      />
      <Input
        name="email"
        type="email"
        autoComplete="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder={t("auth.signup.emailPlaceholder")}
        disabled={busy}
      />
      <Input
        name="password"
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder={t("auth.signup.passwordPlaceholder")}
        disabled={busy}
      />
      <Button type="submit" disabled={busy}>
        {busy ? t("auth.signup.submitting") : t("auth.signup.submit")}
      </Button>
    </form>
  );
}
