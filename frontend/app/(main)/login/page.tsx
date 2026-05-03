"use client";

import Link from "next/link";
import { useState } from "react";
import { resolveI18nText, type I18nText } from "../../../lib/i18n/message";
import { IntroEntryGate } from "../../components/IntroEntryGate";
import { useT } from "../../components/i18n/I18nProvider";
import { PageShell } from "../../components/PageShell";
import { SocialAuthSection } from "../../components/SocialAuthSection";
import { Card, Toast } from "../../components/ui";

export default function LoginPage() {
  const { t } = useT("LoginPage");
  const [error, setError] = useState<I18nText>(null);

  return (
    <IntroEntryGate>
      <PageShell className="auth-page-shell">
        <div className="auth-page-shell__panel">
          <div style={{ textAlign: "center", marginBottom: 18 }}>
            <div className="h2" style={{ fontSize: 28, letterSpacing: "-0.04em", fontWeight: 950 }}>
              {t("auth.login.heroTitle")}
            </div>
            <div className="subtitle" style={{ marginTop: 10, opacity: 0.85 }}>
              {t("auth.login.heroSubtitle")}
            </div>
            <div style={{ marginTop: 14 }}>
              <Link href="/intro" className="btn btn-ghost intro-what-link">
                {t("auth.login.whatIsNeyra")}
              </Link>
            </div>
          </div>

          <Card className="surface auth-card" style={{ paddingTop: 18 }}>
            <div className="auth-card__stack">
              <SocialAuthSection onError={setError} />
              <div className="caption" style={{ marginTop: 14, opacity: 0.75, textAlign: "center" }}>
                {t("auth.login.terms")}
              </div>
            </div>
          </Card>
        </div>
      </PageShell>
      <Toast text={resolveI18nText(error, t)} onClose={() => setError(null)} />
    </IntroEntryGate>
  );
}
