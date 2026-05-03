"use client";

import Link from "next/link";
import { PageShell } from "../PageShell";
import { Card } from "../ui";
import { useT } from "../i18n/I18nProvider";

export function DiscoverGuestPreview() {
  const { t } = useT("DiscoverSwipe");

  return (
    <PageShell className="discover-swipe-shell">
      <div style={{ maxWidth: 520, margin: "0 auto", width: "100%", padding: "24px 18px 40px" }}>
        <div className="h2" style={{ fontSize: 24, fontWeight: 950, letterSpacing: "-0.03em" }}>
          {t("discover.guest.title")}
        </div>
        <div className="subtitle" style={{ marginTop: 10, opacity: 0.88, lineHeight: 1.45 }}>
          {t("discover.guest.subtitle")}
        </div>
        <div style={{ marginTop: 18, display: "flex", gap: 10, flexWrap: "wrap" }}>
          <Link href="/signup" className="btn btn-primary">
            {t("discover.guest.ctaSignup")}
          </Link>
          <Link href="/login" className="btn btn-secondary">
            {t("discover.guest.ctaLogin")}
          </Link>
        </div>

        <Card className="surface" style={{ marginTop: 28, padding: 18, opacity: 0.92 }}>
          <div className="section-label">{t("discover.guest.previewBadge")}</div>
          <div style={{ marginTop: 12, borderRadius: 22, overflow: "hidden", aspectRatio: "3 / 4", background: "linear-gradient(145deg, rgba(124,92,255,0.35), rgba(79,140,255,0.12))" }} />
          <div className="caption" style={{ marginTop: 12, opacity: 0.85, lineHeight: 1.4 }}>
            {t("trust.realPeople")}
          </div>
        </Card>
      </div>
    </PageShell>
  );
}
