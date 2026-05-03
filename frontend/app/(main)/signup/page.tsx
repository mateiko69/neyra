"use client";

import Link from "next/link";
import { Suspense, useEffect, useRef, useState } from "react";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { markSignupFlowFromSignupPage } from "../../../lib/referralSignupFlow";
import { resolveI18nText, type I18nText } from "../../../lib/i18n/message";
import { EmailPasswordSignupCard } from "../../components/auth/EmailPasswordSignupCard";
import { IntroEntryGate } from "../../components/IntroEntryGate";
import { useT } from "../../components/i18n/I18nProvider";
import { PageHeader } from "../../components/PageHeader";
import { PageShell } from "../../components/PageShell";
import { SocialAuthSection } from "../../components/SocialAuthSection";
import { Card, Toast } from "../../components/ui";

export default function SignupPage() {
  const { t } = useT("SignupPage");
  const [formError, setFormError] = useState<I18nText>(null);
  const startedTracked = useRef(false);

  useEffect(() => {
    markSignupFlowFromSignupPage();
    if (startedTracked.current) return;
    startedTracked.current = true;
    void trackAnalyticsEvent("signup_started", { source: "signup_page" });
  }, []);

  return (
    <IntroEntryGate>
      <PageShell className="auth-page-shell">
        <div className="auth-page-shell__panel">
          <PageHeader variant="hero" title={t("auth.signup.title")} subtitle={t("auth.signup.subtitle")} />
          <div style={{ textAlign: "center", margin: "-6px 0 14px" }}>
            <Link href="/intro" className="btn btn-ghost intro-what-link">
              {t("auth.signup.whatIsNeyra")}
            </Link>
          </div>
          <Card className="surface auth-card">
            <div className="auth-card__stack">
              <Suspense
                fallback={
                  <div className="caption" style={{ opacity: 0.8, textAlign: "center" }}>
                    {t("common.loading")}
                  </div>
                }
              >
                <EmailPasswordSignupCard onError={setFormError} />
              </Suspense>
              <SocialAuthSection onError={setFormError} />

              <div className="auth-form__footer">
                <div className="auth-form__footer-row">
                  <span>{t("auth.signup.haveAccount")}</span>
                  <Link href="/login" className="auth-form__link">
                    {t("nav.login")}
                  </Link>
                </div>
                <Link href="/discover" className="auth-form__muted-link">
                  {t("auth.common.skip")}
                </Link>
              </div>
            </div>
          </Card>
        </div>
      </PageShell>
      <Toast text={resolveI18nText(formError, t)} onClose={() => setFormError(null)} />
    </IntroEntryGate>
  );
}
