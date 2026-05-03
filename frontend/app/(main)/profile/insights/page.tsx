"use client";

import Link from "next/link";
import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, getToken } from "../../../../lib/api";
import { PageShell } from "../../../components/PageShell";
import { PageHeader } from "../../../components/PageHeader";
import { Card, Button, Toast, Badge } from "../../../components/ui";
import { useT } from "../../../components/i18n/I18nProvider";
import { trackAnalyticsEvent } from "../../../../lib/analytics";

type InsightAction = { id: string; label: string };

type Insight = {
  id: string;
  title: string;
  body: string;
  confidence?: number;
  evidence?: Record<string, unknown>;
  actions?: InsightAction[];
};

type InsightsResponse = {
  insights: Insight[];
  aggregates?: unknown;
  generated_at?: string | null;
  actions_state?: { experiments?: unknown[]; preferences?: Record<string, unknown> };
  privacy?: { note?: string };
};

export default function ProfileInsightsPage() {
  const router = useRouter();
  const { t } = useT("ProfilePage");
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<InsightsResponse | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const raw = await apiFetch("/ai/insights/me", { metaReason: "pattern-insights-me", skipThrottle: true });
      setData(raw && typeof raw === "object" ? (raw as InsightsResponse) : null);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    void load();
  }, [router, load]);

  async function runAction(insightId: string, actionId: string) {
    const key = `${insightId}:${actionId}`;
    if (busyKey) return;
    setBusyKey(key);
    try {
      await apiFetch("/ai/insights/actions", {
        method: "POST",
        metaReason: "pattern-insights-action",
        skipThrottle: true,
        body: JSON.stringify({ insight_id: insightId, action_id: actionId }),
      });
      setToast(t("profile.insights.actionSaved"));
      void trackAnalyticsEvent("pattern_insight_action_click", { insight_id: insightId, action_id: actionId });
      await load();
    } catch {
      setToast(t("profile.insights.actionError"));
    } finally {
      setBusyKey(null);
    }
  }

  async function sendFeedback(insightId: string, helpful: boolean) {
    try {
      await apiFetch("/ai/insights/feedback", {
        method: "POST",
        metaReason: "pattern-insights-feedback",
        skipThrottle: true,
        body: JSON.stringify({ insight_id: insightId, helpful }),
      });
      setToast(helpful ? t("profile.insights.thanksHelpful") : t("profile.insights.thanksFeedback"));
    } catch {
      /* ignore */
    }
  }

  const insights = data?.insights ?? [];

  return (
    <PageShell>
      <PageHeader
        variant="hero"
        title={t("profile.insights.title")}
        subtitle={t("profile.insights.subtitle")}
        badge={<Badge tone="premium">{t("profile.insights.privateBadge")}</Badge>}
      />

      <div className="caption" style={{ marginTop: -8, marginBottom: 16, maxWidth: "68ch", lineHeight: 1.5, opacity: 0.88 }}>
        {t("profile.insights.privacyLine")}
      </div>

      <div style={{ marginBottom: 16 }}>
        <Link href="/profile" className="text-link">
          ← {t("profile.insights.back")}
        </Link>
      </div>

      {loading ? (
        <Card className="surface surface--inset">
          <div className="body">{t("profile.insights.loading")}</div>
        </Card>
      ) : insights.length === 0 ? (
        <Card className="surface surface--inset">
          <div className="h2" style={{ fontSize: 18 }}>
            {t("profile.insights.emptyTitle")}
          </div>
          <p className="body" style={{ marginTop: 8, opacity: 0.9 }}>
            {t("profile.insights.emptyBody")}
          </p>
        </Card>
      ) : (
        <div style={{ display: "grid", gap: 14 }}>
          {insights.map((ins) => (
            <Card key={ins.id} className="surface surface--inset pattern-insight-card">
              <div className="section-label" style={{ fontSize: 15 }}>
                {ins.title}
              </div>
              <p className="body" style={{ marginTop: 8, lineHeight: 1.55 }}>
                {ins.body}
              </p>
              {typeof ins.confidence === "number" ? (
                <div className="caption" style={{ marginTop: 8, opacity: 0.75 }}>
                  {t("profile.insights.confidence", { percent: Math.round(ins.confidence * 100) })}
                </div>
              ) : null}
              <div style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 8 }}>
                {(ins.actions ?? []).map((a) => (
                  <Button
                    key={a.id}
                    type="button"
                    variant={a.id === "try_7_days" ? "primary" : "secondary"}
                    disabled={busyKey != null}
                    onClick={() => void runAction(ins.id, a.id)}
                  >
                    {a.label}
                  </Button>
                ))}
                <Button type="button" variant="ghost" onClick={() => void sendFeedback(ins.id, true)}>
                  {t("profile.insights.helpful")}
                </Button>
                <Button type="button" variant="ghost" onClick={() => void sendFeedback(ins.id, false)}>
                  {t("profile.insights.notForMe")}
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Toast text={toast} onClose={() => setToast(null)} />
    </PageShell>
  );
}
