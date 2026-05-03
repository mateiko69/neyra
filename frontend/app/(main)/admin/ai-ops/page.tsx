"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch, formatApiError } from "../../../../lib/api";
import { PageHeader } from "../../../components/PageHeader";
import { PageShell } from "../../../components/PageShell";
import { Badge, Card, Skeleton } from "../../../components/ui";
import { useT } from "../../../components/i18n/I18nProvider";

export default function AdminAiOpsPage() {
  const { t } = useT("AdminAiOpsPage");
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        const res = await apiFetch("/admin/ai-ops-insights", {
          method: "GET",
          metaReason: "admin-ai-ops",
          skipThrottle: true,
        });
        setData(res as Record<string, unknown>);
      } catch (e: unknown) {
        setErr(formatApiError(e instanceof Error ? e.message : String(e), 0));
      }
    })();
  }, []);

  return (
    <PageShell>
      <PageHeader
        variant="section"
        title={t("admin.aiOps.title")}
        subtitle={
          err
            ? err
            : t("admin.aiOps.subtitle")
        }
        badge={<Badge tone="streak">{t("admin.badge.internal")}</Badge>}
        status={data ? t("common.loaded") : t("common.loading")}
      />
      <div style={{ marginBottom: 12 }}>
        <Link href="/admin/ai-quality" className="btn btn-secondary">
          {t("admin.aiQualityDashboard.link")}
        </Link>
      </div>
      {!data ? (
        <Skeleton style={{ height: 200, borderRadius: 20 }} />
      ) : (
        <Card className="surface">
          <div className="section-label">GET /admin/ai-ops-insights</div>
          <pre className="caption" style={{ whiteSpace: "pre-wrap", margin: "12px 0 0" }}>
            {JSON.stringify(data, null, 2)}
          </pre>
        </Card>
      )}
    </PageShell>
  );
}
