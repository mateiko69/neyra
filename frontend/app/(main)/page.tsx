"use client";

import Link from "next/link";
import { useEffect } from "react";
import { trackAnalyticsEvent } from "../../lib/analytics";
import { useT } from "../components/i18n/I18nProvider";
import { PageHeader } from "../components/PageHeader";
import { PageShell } from "../components/PageShell";
import { Card } from "../components/ui";
import { FirstImpressionIntro } from "../components/FirstImpressionIntro";
import { PublicMarketingShell } from "../components/public/PublicMarketingShell";

export default function Page() {
  const { t } = useT("LandingPage");
  const { t: tAll } = useT();
  useEffect(() => {
    try {
      if (sessionStorage.getItem("neyra:landing_view_tracked") === "1") return;
      sessionStorage.setItem("neyra:landing_view_tracked", "1");
    } catch {
      /* ignore */
    }
    void trackAnalyticsEvent("landing_view", { source: "landing" });
  }, []);

  return (
    <PublicMarketingShell>
      <div className="public-marketing-landing">
        <PageShell>
      <PageHeader
        title={t("brand.name")}
        subtitle={t("landing.subtitle")}
        status={t("landing.status")}
      />

      <div style={{ maxWidth: 980, margin: "0 auto", width: "100%", padding: "0 14px 8px" }}>
        <p className="body muted" style={{ margin: "0 0 20px", lineHeight: 1.6, maxWidth: "62ch" }}>
          {t("landing.hero.lead")}
        </p>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 12,
            alignItems: "center",
            marginBottom: 22,
          }}
        >
          <Link className="btn btn-primary" href="/signup">
            {t("landing.cta.startFree")}
          </Link>
          <Link className="btn btn-secondary" href="/premium">
            {t("landing.cta.viewPremium")}
          </Link>
          <Link className="btn btn-ghost" href="/login?next=/discover">
            {tAll("landing.previewDiscover")}
          </Link>
        </div>

        <FirstImpressionIntro />

        <div style={{ height: 24 }} />

        <div className="section-label">{t("landing.features.eyebrow")}</div>
        <h2 className="h2" style={{ marginTop: 8, marginBottom: 18 }}>
          {t("landing.features.title")}
        </h2>
        <div className="grid grid-2">
          <Card className="surface">
            <div className="section-label">{t("landing.features.ai.title")}</div>
            <p className="body muted" style={{ margin: "10px 0 0", lineHeight: 1.65 }}>
              {t("landing.features.ai.body")}
            </p>
          </Card>
          <Card className="surface surface--inset">
            <div className="section-label">{t("landing.features.discover.title")}</div>
            <p className="body muted" style={{ margin: "10px 0 0", lineHeight: 1.65 }}>
              {t("landing.features.discover.body")}
            </p>
          </Card>
          <Card className="surface surface--inset">
            <div className="section-label">{t("landing.features.chat.title")}</div>
            <p className="body muted" style={{ margin: "10px 0 0", lineHeight: 1.65 }}>
              {t("landing.features.chat.body")}
            </p>
          </Card>
          <Card className="surface">
            <div className="section-label">{t("landing.features.safety.title")}</div>
            <p className="body muted" style={{ margin: "10px 0 0", lineHeight: 1.65 }}>
              {t("landing.features.safety.body")}
            </p>
          </Card>
        </div>

        <div style={{ height: 36 }} />

        <div className="section-label">{t("landing.pricing.eyebrow")}</div>
        <h2 className="h2" style={{ marginTop: 8, marginBottom: 8 }}>
          {t("landing.pricing.title")}
        </h2>
        <p className="body muted" style={{ margin: "0 0 18px", maxWidth: "56ch", lineHeight: 1.55 }}>
          {t("landing.pricing.subtitle")}
        </p>

        <div className="grid grid-3">
          <Card className="surface">
            <div className="section-label">{t("landing.pricing.free.name")}</div>
            <div className="h2" style={{ margin: "6px 0 12px", fontSize: 26, fontWeight: 950 }}>
              {t("landing.pricing.free.price")}
            </div>
            <ul className="body muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.65 }}>
              <li>{t("landing.pricing.free.line1")}</li>
              <li>{t("landing.pricing.free.line2")}</li>
            </ul>
          </Card>
          <Card className="surface surface--inset" style={{ boxShadow: "var(--glow-violet)" }}>
            <div className="section-label">{t("landing.pricing.premium.name")}</div>
            <div className="h2" style={{ margin: "6px 0 12px", fontSize: 26, fontWeight: 950 }}>
              {t("landing.pricing.premium.price")}
            </div>
            <ul className="body muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.65 }}>
              <li>{t("landing.pricing.premium.line1")}</li>
              <li>{t("landing.pricing.premium.line2")}</li>
            </ul>
          </Card>
          <Card className="surface">
            <div className="section-label">{t("landing.pricing.plus.name")}</div>
            <div className="h2" style={{ margin: "6px 0 12px", fontSize: 26, fontWeight: 950 }}>
              {t("landing.pricing.plus.price")}
            </div>
            <ul className="body muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.65 }}>
              <li>{t("landing.pricing.plus.line1")}</li>
              <li>{t("landing.pricing.plus.line2")}</li>
            </ul>
          </Card>
        </div>
        <p className="body muted" style={{ margin: "14px 0 6px", fontSize: 13, lineHeight: 1.5 }}>
          {t("landing.pricing.note")}
        </p>
        <Link className="btn btn-secondary" href="/premium" style={{ display: "inline-flex", marginTop: 8 }}>
          {t("landing.pricing.fullComparison")}
        </Link>

        <div style={{ height: 36 }} />

        <div className="section-label">{t("landing.trust.eyebrow")}</div>
        <h2 className="h2" style={{ marginTop: 8, marginBottom: 14 }}>
          {t("landing.trust.title")}
        </h2>
        <Card className="surface surface--inset">
          <ul className="body muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
            <li style={{ marginBottom: 10 }}>{t("landing.trust.item1")}</li>
            <li style={{ marginBottom: 10 }}>{t("landing.trust.item2")}</li>
            <li>{t("landing.trust.item3")}</li>
          </ul>
        </Card>

        <div style={{ height: 28 }} />

        <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
          <Link className="btn btn-primary" href="/signup">
            {t("landing.cta.startFree")}
          </Link>
          <Link className="btn btn-secondary" href="/premium">
            {t("landing.cta.viewPremium")}
          </Link>
        </div>

        <div style={{ height: 28 }} />
      </div>
    </PageShell>
      </div>
    </PublicMarketingShell>
  );
}
