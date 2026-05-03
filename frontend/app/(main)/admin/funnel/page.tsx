"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../../../../lib/api";
import { PageHeader } from "../../../components/PageHeader";
import { PageShell } from "../../../components/PageShell";
import { Badge, Card, Chip, Skeleton } from "../../../components/ui";
import { useT } from "../../../components/i18n/I18nProvider";

type FunnelResponse = {
  window_days: number;
  since: string;
  events: Record<string, { events: number; users: number }>;
  stages: Array<{ key: string; label: string; event: string; users: number }>;
  conversions: Array<{ from: string; to: string; from_users: number; to_users: number; rate: number | null }>;
  ai_split: {
    first_message_users: number;
    ai_assisted_users: number;
    non_ai_users: number;
    ai_assisted_rate: number | null;
  };
};

function pct(x: number | null): string {
  if (x == null) return "—";
  return `${Math.round(x * 100)}%`;
}

export default function AdminFunnelPage() {
  const { t } = useT("AdminFunnelPage");
  const [days, setDays] = useState(7);
  const [data, setData] = useState<FunnelResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (typeof process !== "undefined" && process.env.NODE_ENV === "production") {
      // Backend is admin-gated already; keep UI conservative in prod.
      return;
    }
    setFailed(false);
    setData(null);
    apiFetch(`/admin/funnel?days=${days}`, { metaReason: "admin-funnel", skipThrottle: true, skipCache: true })
      .then((res) => setData(res as FunnelResponse))
      .catch(() => setFailed(true));
  }, [days]);

  const stageByKey = useMemo(() => {
    const map = new Map<string, { label: string; users: number }>();
    (data?.stages || []).forEach((s) => map.set(s.key, { label: s.label, users: s.users }));
    return map;
  }, [data?.stages]);

  return (
    <PageShell>
      <PageHeader
        variant="section"
        title={t("admin.funnel.title")}
        subtitle={t("admin.funnel.subtitle")}
        badge={<Badge tone="streak">{t("admin.internal")}</Badge>}
        status={data ? t("admin.funnel.window", { days: data.window_days }) : "—"}
      />

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
        {[1, 7, 30].map((d) => (
          <button
            key={d}
            type="button"
            className={`btn ${days === d ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setDays(d)}
          >
            {d}d
          </button>
        ))}
        {data ? <Chip>{t("admin.funnel.since", { value: new Date(data.since).toLocaleString() })}</Chip> : null}
      </div>

      {!data && !failed ? <Skeleton style={{ height: 140, borderRadius: 22 }} /> : null}
      {failed ? (
        <Card className="surface" style={{ padding: 16 }}>
          <div className="section-label">{t("admin.unavailable.title")}</div>
          <div className="caption">{t("admin.unavailable.subtitle")}</div>
        </Card>
      ) : null}

      {data ? (
        <>
          <div className="grid grid-2">
            <Card className="surface">
              <div className="section-label">{t("admin.funnel.stageCounts")}</div>
              <pre className="caption" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                {JSON.stringify(data.stages, null, 2)}
              </pre>
            </Card>
            <Card className="surface surface--inset">
              <div className="section-label">{t("admin.funnel.conversions")}</div>
              <pre className="caption" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                {JSON.stringify(
                  data.conversions.map((c) => ({ ...c, rate: c.rate == null ? null : `${Math.round(c.rate * 100)}%` })),
                  null,
                  2,
                )}
              </pre>
            </Card>
          </div>

          <div style={{ height: 14 }} />

          <div className="grid grid-2">
            <Card className="surface">
              <div className="section-label">{t("admin.funnel.aiSplit")}</div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                <Chip>{t("admin.funnel.aiSplit.firstMessageUsers", { value: data.ai_split.first_message_users })}</Chip>
                <Chip>{t("admin.funnel.aiSplit.aiAssisted", { value: data.ai_split.ai_assisted_users })}</Chip>
                <Chip>{t("admin.funnel.aiSplit.nonAi", { value: data.ai_split.non_ai_users })}</Chip>
                <Chip>{t("admin.funnel.aiSplit.share", { value: pct(data.ai_split.ai_assisted_rate) })}</Chip>
              </div>
            </Card>
            <Card className="surface surface--inset">
              <div className="section-label">{t("admin.funnel.rawEvents")}</div>
              <pre className="caption" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                {JSON.stringify(data.events, null, 2)}
              </pre>
            </Card>
          </div>
        </>
      ) : null}
    </PageShell>
  );
}

