"use client";

import { useMemo, useState } from "react";
import { readLocalAnalyticsEvents, clearLocalAnalyticsEvents } from "../../../../lib/analyticsLocalStore";
import { computeDashboardMetrics, type WindowKey } from "../../../../lib/dashboard/computeMetrics";
import { EVENT_MAPPING } from "../../../../lib/dashboard/eventMetricMapping";
import { PageHeader } from "../../../components/PageHeader";
import { PageShell } from "../../../components/PageShell";
import { Badge, Button, Card, Chip } from "../../../components/ui";
import { useT } from "../../../components/i18n/I18nProvider";

const WINDOWS: { key: WindowKey; label: string }[] = [
  { key: "session", label: "admin.dashboard.window.session" },
  { key: "today", label: "admin.dashboard.window.today" },
  { key: "7d", label: "7d" },
  { key: "30d", label: "30d" },
];

function pct(x: number | null): string {
  if (x == null) return "—";
  return `${Math.round(x * 100)}%`;
}

export default function ProductDashboardPage() {
  const { t } = useT("AdminDashboardPage");
  const [windowKey, setWindowKey] = useState<WindowKey>("today");
  const events = useMemo(() => readLocalAnalyticsEvents(), []);
  const metrics = useMemo(() => computeDashboardMetrics(events, windowKey), [events, windowKey]);

  const sortedCounts = useMemo(() => {
    const rows = Object.entries(metrics.counts).map(([k, v]) => ({ k, v }));
    rows.sort((a, b) => b.v - a.v);
    return rows.slice(0, 40);
  }, [metrics.counts]);

  return (
    <PageShell>
      <PageHeader
        variant="section"
        title={t("admin.dashboard.title")}
        subtitle={t("admin.dashboard.subtitle")}
        badge={<Badge tone="streak">{t("admin.internal")}</Badge>}
        status={t("admin.dashboard.status", { count: events.length })}
      />

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
        {WINDOWS.map((w) => (
          <button
            key={w.key}
            type="button"
            className={`btn ${windowKey === w.key ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setWindowKey(w.key)}
          >
            {w.label.startsWith("admin.") ? t(w.label) : w.label}
          </button>
        ))}
        <Button
          variant="ghost"
          onClick={() => {
            clearLocalAnalyticsEvents();
            window.location.reload();
          }}
        >
          {t("admin.dashboard.clear")}
        </Button>
      </div>

      <div className="grid grid-2">
        <Card className="surface">
          <div className="section-label">{t("admin.dashboard.aiEffectiveness")}</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
            <Chip>{t("admin.dashboard.ai.usage", { value: pct(metrics.rates.ai_assist_usage_rate ?? null) })}</Chip>
            <Chip>{t("admin.dashboard.ai.replySuccess", { value: pct(metrics.rates.ai_assist_success_reply_received_rate ?? null) })}</Chip>
            <Chip>{t("admin.dashboard.ai.readiness", { value: pct(metrics.rates.ai_assist_success_readiness_improved_rate ?? null) })}</Chip>
            <Chip>{t("admin.dashboard.ai.recovery", { value: pct(metrics.rates.ai_assist_success_recovery_worked_rate ?? null) })}</Chip>
            <Chip>{t("admin.dashboard.ai.escalation", { value: pct(metrics.rates.ai_assist_success_escalation_progressed_rate ?? null) })}</Chip>
          </div>
        </Card>

        <Card className="surface surface--inset">
          <div className="section-label">{t("admin.dashboard.plusHooks")}</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
            <Chip>{t("admin.dashboard.plus.ctr", { value: pct(metrics.rates.premium_plus_hook_ctr ?? null) })}</Chip>
            <Chip>{t("admin.dashboard.plus.conversion", { value: pct(metrics.rates.premium_plus_hook_conversion_rate ?? null) })}</Chip>
          </div>
          <div style={{ height: 12 }} />
          <div className="caption">{t("admin.dashboard.topContexts")}</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
            {(metrics.topContexts.length ? metrics.topContexts : [{ key: "—", count: 0 }]).map((r) => (
              <Chip key={r.key}>
                {r.key}: {r.count}
              </Chip>
            ))}
          </div>
          <div style={{ height: 12 }} />
          <div className="caption">{t("admin.dashboard.topVariants")}</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
            {(metrics.topVariants.length ? metrics.topVariants : [{ key: "—", count: 0 }]).map((r) => (
              <Chip key={r.key}>
                {r.key}: {r.count}
              </Chip>
            ))}
          </div>
        </Card>
      </div>

      <div style={{ height: 14 }} />

      <div className="grid grid-2">
        <Card className="surface">
          <div className="section-label">{t("admin.dashboard.eventCounts")}</div>
          <pre className="caption" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
            {JSON.stringify(
              sortedCounts.map((r) => ({ event: r.k, count: r.v, note: EVENT_MAPPING[r.k] ?? "" })),
              null,
              2,
            )}
          </pre>
        </Card>
        <Card className="surface surface--inset">
          <div className="section-label">{t("admin.dashboard.rawLast")}</div>
          <pre className="caption" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
            {JSON.stringify(events.slice(-120), null, 2)}
          </pre>
        </Card>
      </div>
    </PageShell>
  );
}

