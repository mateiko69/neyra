"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch, formatApiError } from "../../../../lib/api";
import { PageHeader } from "../../../components/PageHeader";
import { PageShell } from "../../../components/PageShell";
import { Badge, Card, Skeleton, Chip } from "../../../components/ui";
import { useT } from "../../../components/i18n/I18nProvider";
import { translateApiUserMessage } from "../../../../lib/i18n/translateApiUserMessage";

function pct(x: number | null | undefined): string {
  if (x == null) return "—";
  return `${Math.round(x * 100)}%`;
}

export default function AdminAiQualityPage() {
  const { t } = useT("AdminAiQualityPage");
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<string>("");

  useEffect(() => {
    void (async () => {
      try {
        const res = await apiFetch("/admin/ai-quality", { method: "GET", metaReason: "admin-ai-quality", skipThrottle: true });
        setData(res);
      } catch (e: unknown) {
        const raw = e instanceof Error ? e.message : String(e);
        setErr(translateApiUserMessage(raw.trim(), t).trim() || t("admin.errors.generic"));
      }
    })();
  }, [t]);

  const summary = data?.summary ?? null;
  const styles = data?.styles ?? {};
  const sources = data?.sources ?? {};
  const flags: any[] = Array.isArray(data?.quality_flags) ? data.quality_flags : [];
  const premium = data?.premium ?? null;

  const styleRows = useMemo(() => {
    return ["light", "flirty", "deep"].map((k) => ({ k, ...(styles?.[k] ?? {}) }));
  }, [styles]);

  const sourceRows = useMemo(() => {
    return Object.entries(sources || {}).map(([k, v]) => ({ k, ...(v as any) }));
  }, [sources]);

  return (
    <PageShell>
      <PageHeader
        variant="section"
        title={t("admin.aiQuality.title")}
        subtitle={err ? err : t("admin.aiQuality.subtitle")}
        badge={<Badge tone="streak">{t("admin.internal")}</Badge>}
        status={
          summary
            ? t("admin.aiQuality.statusEvents", { n: summary.ai_events_total ?? 0 })
            : t("admin.aiQuality.statusLoading")
        }
      />

      {!data ? (
        <Skeleton style={{ height: 160, borderRadius: 20 }} />
      ) : (
        <>
          <div className="grid grid-2">
            <Card className="surface">
              <div className="section-label">{t("admin.quality.section.summary")}</div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                <Chip>{t("admin.aiQuality.chipOptionsSelected", { n: summary?.options_selected ?? 0 })}</Chip>
                <Chip>{t("admin.aiQuality.chipSelectionRate", { pct: pct(summary?.selection_rate) })}</Chip>
                <Chip>{t("admin.aiQuality.chipEditedRate", { pct: pct(summary?.edited_rate) })}</Chip>
                <Chip>{t("admin.aiQuality.chipPartnerReply", { pct: pct(summary?.partner_reply_rate) })}</Chip>
                <Chip>{t("admin.aiQuality.chipMeetingSuggest", { pct: pct(summary?.meeting_suggestion_rate) })}</Chip>
                <Chip>{t("admin.aiQuality.chipMeetingRejected", { pct: pct(summary?.meeting_rejected_rate) })}</Chip>
              </div>
            </Card>

            <Card className="surface surface--inset">
              <div className="section-label">{t("admin.quality.section.premium")}</div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                <Chip>{t("admin.aiQuality.chipFreeAiUsers", { n: premium?.free_ai_users ?? 0 })}</Chip>
                <Chip>{t("admin.aiQuality.chipPremiumAiUsers", { n: premium?.premium_ai_users ?? 0 })}</Chip>
                <Chip>{t("admin.aiQuality.chipTrialAfterAi", { n: premium?.trial_started_after_ai ?? 0 })}</Chip>
                <Chip>{t("admin.aiQuality.chipPremiumConvAfterAi", { n: premium?.premium_conversion_after_ai ?? 0 })}</Chip>
              </div>
            </Card>
          </div>

          <div style={{ height: 14 }} />

          <div className="grid grid-2">
            <Card className="surface">
              <div className="section-label">{t("admin.quality.section.stylePerf")}</div>
              <pre className="caption" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                {JSON.stringify(styleRows, null, 2)}
              </pre>
            </Card>
            <Card className="surface surface--inset">
              <div className="section-label">{t("admin.quality.section.sourcePerf")}</div>
              <pre className="caption" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                {JSON.stringify(sourceRows, null, 2)}
              </pre>
            </Card>
          </div>

          <div style={{ height: 14 }} />

          <Card className="surface">
            <div className="section-label">{t("admin.aiQuality.qualityIssuesTitle")}</div>
            {!flags.length ? (
              <div className="caption muted" style={{ marginTop: 8 }}>
                {t("admin.aiQuality.noFlags")}
              </div>
            ) : (
              <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
                {flags.map((f, idx) => (
                  <div key={idx} className="caption">
                    <strong>{String(f.type || "flag")}:</strong> {String(f.message || "")}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </PageShell>
  );
}

