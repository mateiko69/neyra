"use client";

import { useEffect } from "react";
import Link from "next/link";
import { PageShell } from "../../components/PageShell";
import { PageHeader } from "../../components/PageHeader";
import { Card, Button } from "../../components/ui";
import { useT } from "../../components/i18n/I18nProvider";

export default function OnboardingError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const { t } = useT("OnboardingError");
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error("onboarding_error", error);
  }, [error]);

  return (
    <PageShell>
      <PageHeader title={t("errors.title")} subtitle={t("errors.subtitle")} />
      <div className="grid" style={{ maxWidth: 760, margin: "0 auto", width: "100%" }}>
        <Card className="surface" style={{ padding: 18 }}>
          <div className="h2">{t("errors.safeFallbackTitle")}</div>
          <div className="subtitle" style={{ marginTop: 6 }}>
            {t("errors.safeFallbackBody")}
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14 }}>
            <Button type="button" onClick={() => reset()}>
              {t("common.tryAgain")}
            </Button>
            <Link className="btn btn-ghost" href="/login">
              {t("nav.login")}
            </Link>
          </div>
        </Card>
      </div>
    </PageShell>
  );
}

