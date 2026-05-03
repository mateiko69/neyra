"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch } from "../../../lib/api";
import { useT } from "../../components/i18n/I18nProvider";
import { PageHeader } from "../../components/PageHeader";
import { PageShell } from "../../components/PageShell";
import { Badge, Card, Skeleton } from "../../components/ui";

export default function AdminPage() {
  const { t } = useT("AdminPage");
  const [dash, setDash] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);

  useEffect(() => {
    apiFetch("/admin/dashboard").then(setDash).catch(() => {});
    apiFetch("/admin/events").then(setEvents).catch(() => {});
  }, []);

  return (
    <PageShell>
      <PageHeader
        variant="section"
        title={t("admin.header.title")}
        subtitle={t("admin.header.subtitle")}
        badge={<Badge tone="streak">{t("admin.header.badge")}</Badge>}
        status={t("admin.header.status")}
      />
      <Card className="surface surface--inset" style={{ marginBottom: 16 }}>
        <div className="section-label">{t("admin.hub.localizationEyebrow")}</div>
        <h2 className="h2" style={{ fontSize: 18 }}>
          {t("admin.hub.localizationTitle")}
        </h2>
        <div style={{ height: 10 }} />
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
          <Link href="/admin/ai-ops" className="btn btn-secondary">
            AI ops / Gemini
          </Link>
          <Link href="/admin/localization-center" className="btn btn-primary">
            {t("admin.hub.localizationCenterLink")}
          </Link>
          <Link href="/admin/localization-coverage" className="btn btn-secondary">
            {t("admin.hub.coverageLink")}
          </Link>
          <Link href="/admin/localization-quality" className="btn btn-secondary">
            {t("admin.hub.qualityLink")}
          </Link>
        </div>
      </Card>

      <div className="grid grid-2">
        <Card className="surface">
          <div className="section-label">{t("admin.overview.eyebrow")}</div>
          <h2 className="h2" style={{ fontSize: 18 }}>
            {t("admin.overview.title")}
          </h2>
          <div style={{ height: 12 }} />
          {!dash ? <Skeleton style={{ height: 120, borderRadius: 20 }} /> : <pre className="caption" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(dash, null, 2)}</pre>}
        </Card>
        <Card className="surface surface--inset">
          <div className="section-label">{t("admin.stream.eyebrow")}</div>
          <h2 className="h2" style={{ fontSize: 18 }}>
            {t("admin.stream.title")}
          </h2>
          <div style={{ height: 12 }} />
          {!events?.length ? <Skeleton style={{ height: 120, borderRadius: 20 }} /> : <pre className="caption" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(events, null, 2)}</pre>}
        </Card>
      </div>
    </PageShell>
  );
}
