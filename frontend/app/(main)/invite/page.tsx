"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getToken } from "../../../lib/api";
import { useT } from "../../components/i18n/I18nProvider";
import { InviteFriendsCard } from "../../components/InviteFriendsCard";
import { PageHeader } from "../../components/PageHeader";
import { PageShell } from "../../components/PageShell";
import { Button, Card } from "../../components/ui";

export default function InvitePage() {
  const router = useRouter();
  const { t } = useT("InvitePage");
  const [allowed, setAllowed] = useState<boolean | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    setAllowed(true);
  }, [router]);

  if (allowed !== true) {
    return (
      <PageShell>
        <Card className="surface">
          <div className="body muted">{t("common.loading")}</div>
        </Card>
      </PageShell>
    );
  }

  return (
    <PageShell>
      <div className="grid" style={{ maxWidth: 820, margin: "0 auto", width: "100%" }}>
        <PageHeader variant="hero" title={t("referrals.title")} subtitle={t("referrals.subtitle")} />
        <InviteFriendsCard source="invite_page" showRewards />
        <div style={{ marginTop: 12 }}>
          <Button type="button" variant="ghost" onClick={() => router.back()}>
            {t("common.back")}
          </Button>
        </div>
      </div>
    </PageShell>
  );
}
