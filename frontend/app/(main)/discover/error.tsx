"use client";

import { useEffect } from "react";
import Link from "next/link";
import { PageShell } from "../../components/PageShell";
import { PageHeader } from "../../components/PageHeader";
import { Card, Button } from "../../components/ui";
import { useT } from "../../components/i18n/I18nProvider";

export default function DiscoverError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const { t } = useT("DiscoverError");
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error("discover_error", error);
  }, [error]);

  return (
    <PageShell>
      <PageHeader title={t("errors.title")} subtitle={t("errors.subtitle")} />
      <div className="grid" style={{ maxWidth: 820, margin: "0 auto", width: "100%" }}>
        <Card className="surface" style={{ padding: 18 }}>
          <div className="h2">{t("errors.safeFallbackTitle")}</div>
          <div className="subtitle" style={{ marginTop: 6 }}>
            {t("errors.safeFallbackBody")}
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14 }}>
            <Button type="button" onClick={() => reset()}>
              {t("common.tryAgain")}
            </Button>
            <Link className="btn btn-ghost" href="/profile">
              {t("nav.profile")}
            </Link>
          </div>
        </Card>
      </div>
    </PageShell>
  );
}

