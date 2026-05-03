"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiFetch, applyAuthBootstrapResult, getToken, invalidateApiGetCache, setAccessToken } from "../../../lib/api";
import { getAuthBootstrapResult, primeAuthBootstrapFromMe } from "../../../lib/auth/bootstrap";
import { i18nKey, resolveI18nText, type I18nText } from "../../../lib/i18n/message";
import { apiFailureToI18nText } from "../../../lib/i18n/translateApiUserMessage";
import { PageHeader } from "../../components/PageHeader";
import { PageShell } from "../../components/PageShell";
import { Button, Card, Toast } from "../../components/ui";
import { useT } from "../../components/i18n/I18nProvider";

type Phase = "idle" | "verifying" | "success" | "error";

export default function VerifyEmailPage() {
  const { t } = useT("VerifyEmailPage");
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("idle");
  const [toast, setToast] = useState<I18nText>(null);
  const [resendBusy, setResendBusy] = useState(false);

  const redirectAfterSession = useCallback(
    async (accessToken: string) => {
      setAccessToken(accessToken);
      invalidateApiGetCache("/auth/me");
      try {
        const me = await apiFetch("/auth/me", { method: "GET", metaReason: "verify-email-after-verify", skipThrottle: true });
        primeAuthBootstrapFromMe(me);
        await getAuthBootstrapResult({ force: true }).then(applyAuthBootstrapResult);
        const onboardingRequired = Boolean(me && typeof me === "object" ? (me as any).onboarding_required : false);
        router.replace(onboardingRequired ? "/onboarding" : "/discover");
      } catch {
        router.replace("/discover");
      }
    },
    [router],
  );

  useEffect(() => {
    if (typeof window === "undefined") return;
    const q = new URLSearchParams(window.location.search);
    const token = (q.get("token") || "").trim();
    if (!token) {
      setPhase("idle");
      return;
    }
    let cancelled = false;
    setPhase("verifying");
    void (async () => {
      try {
        const res = (await apiFetch("/auth/verify-email", {
          method: "POST",
          metaReason: "verify-email-token",
          body: JSON.stringify({ token }),
          skipThrottle: true,
        })) as { ok?: boolean; access_token?: string; email_verified?: boolean };
        if (cancelled) return;
        const tok = typeof res?.access_token === "string" ? res.access_token.trim() : "";
        if (res?.ok && tok) {
          setPhase("success");
          window.setTimeout(() => {
            void redirectAfterSession(tok);
          }, 900);
          return;
        }
        setPhase("error");
      } catch {
        if (cancelled) return;
        setPhase("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [redirectAfterSession]);

  async function onResend() {
    if (resendBusy) return;
    setResendBusy(true);
    try {
      await apiFetch("/auth/verify-email/resend", { method: "POST", metaReason: "verify-email-resend", body: JSON.stringify({}) });
      setToast(i18nKey("verifyEmail.resendOk"));
    } catch (e) {
      setToast(apiFailureToI18nText(e, t, "verifyEmail.errors.invalidOrExpired"));
    } finally {
      setResendBusy(false);
    }
  }

  const subtitle =
    phase === "verifying"
      ? t("verifyEmail.subtitleVerifying")
      : phase === "success"
        ? t("verifyEmail.subtitleOk")
        : phase === "error"
          ? t("verifyEmail.subtitleError")
          : phase === "idle"
            ? t("verifyEmail.subtitleMissing")
            : t("verifyEmail.subtitleMissing");

  return (
    <>
      <PageShell>
        <PageHeader title={t("verifyEmail.title")} subtitle={subtitle} />
        <Card className="surface" style={{ padding: 18 }}>
          {phase === "verifying" ? (
            <p className="body" style={{ marginTop: 0 }}>
              {t("verifyEmail.verifyingBody")}
            </p>
          ) : null}

          {phase === "success" ? (
            <p className="body" style={{ marginTop: 0 }}>
              {t("verifyEmail.okBody")}
            </p>
          ) : null}

          {phase === "error" ? (
            <>
              <p className="body" style={{ marginTop: 0 }}>
                {t("verifyEmail.errorBody")}
              </p>
              <p className="caption" style={{ marginTop: 10, opacity: 0.88, lineHeight: 1.45 }}>
                {t("verifyEmail.errors.tryResend")}
              </p>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14 }}>
                <Link className="btn btn-primary" href="/login">
                  {t("nav.login")}
                </Link>
                {getToken() ? (
                  <Button type="button" variant="secondary" disabled={resendBusy} onClick={() => void onResend()}>
                    {t("verifyEmail.resendCta")}
                  </Button>
                ) : (
                  <span className="caption" style={{ opacity: 0.85, alignSelf: "center" }}>
                    {t("verifyEmail.loginToResend")}
                  </span>
                )}
              </div>
            </>
          ) : null}

          {phase === "idle" && (
            <p className="body" style={{ marginTop: 0 }}>
              {t("verifyEmail.missingToken")}
            </p>
          )}

          {phase !== "verifying" ? (
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14 }}>
              <Link className="btn btn-ghost" href="/signup">
                {t("nav.signup")}
              </Link>
            </div>
          ) : null}
        </Card>
      </PageShell>
      <Toast text={resolveI18nText(toast, t)} onClose={() => setToast(null)} />
    </>
  );
}
