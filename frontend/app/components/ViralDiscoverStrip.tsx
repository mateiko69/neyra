"use client";

import { useEffect, useState } from "react";
import { apiFetch, getToken } from "../../lib/api";
import { trackAnalyticsEvent } from "../../lib/analytics";
import { useT } from "./i18n/I18nProvider";

type ViralContext = {
  social_proof?: { joining_today_count?: number; show_banner?: boolean };
  visibility_loop?: { tier?: string; activity_points?: number };
  profile_highlight?: { eligible?: boolean; strength?: string };
};

export function ViralDiscoverStrip() {
  const { t } = useT("ViralDiscoverStrip");
  const [ctx, setCtx] = useState<ViralContext | null>(null);

  useEffect(() => {
    if (!getToken()) return;
    let cancelled = false;
    void apiFetch("/growth/viral-context", { metaReason: "viral-context:discover", skipThrottle: true })
      .then((r) => {
        if (cancelled || !r || typeof r !== "object") return;
        setCtx(r as ViralContext);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (!ctx) return null;

  const sp = ctx.social_proof;
  const vis = ctx.visibility_loop;
  const ph = ctx.profile_highlight;

  const showSocial = Boolean(sp?.show_banner && (sp?.joining_today_count ?? 0) >= 3);
  const tier = (vis?.tier ?? "low").toLowerCase();
  const visibilityLine =
    tier === "high"
      ? t("viral.visibility.high")
      : tier === "medium"
        ? t("viral.visibility.medium")
        : t("viral.visibility.low");
  const showHighlight = Boolean(ph?.eligible && ph?.strength === "high");
  const suppressInvite = (() => {
    if (typeof window === "undefined") return false;
    try {
      const raw = sessionStorage.getItem("neyra:hide_invite_until");
      const ts = raw ? Number(raw) : 0;
      return Number.isFinite(ts) && ts > Date.now();
    } catch {
      return false;
    }
  })();

  if (!showSocial && !showHighlight) {
    return (
      <div
        className="caption muted"
        style={{
          marginBottom: 12,
          padding: "8px 12px",
          borderRadius: 12,
          background: "rgba(255,255,255,0.04)",
          border: "1px solid rgba(255,255,255,0.08)",
        }}
      >
        {visibilityLine}
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 8, marginBottom: 14 }}>
      {showSocial ? (
        <div
          className="caption"
          style={{
            padding: "8px 12px",
            borderRadius: 12,
            background: "rgba(120,200,255,0.08)",
            border: "1px solid rgba(120,200,255,0.2)",
          }}
        >
          {t("viral.socialProof", { count: sp?.joining_today_count ?? 0 })}
        </div>
      ) : null}
      <div
        className="caption muted"
        style={{
          padding: "8px 12px",
          borderRadius: 12,
          background: "rgba(255,255,255,0.04)",
          border: "1px solid rgba(255,255,255,0.08)",
        }}
      >
        {visibilityLine}
      </div>
      {showHighlight && !suppressInvite ? (
        <button
          type="button"
          className="caption"
          style={{
            textAlign: "left",
            padding: "8px 12px",
            borderRadius: 12,
            background: "rgba(180,140,255,0.1)",
            border: "1px solid rgba(180,140,255,0.25)",
            color: "inherit",
            cursor: "pointer",
          }}
          onClick={() => {
            void trackAnalyticsEvent("viral_top_profile_cta", { strength: ph?.strength ?? "" });
            window.location.href = "/invite?source=top_profile_today";
          }}
        >
          {t("viral.topProfile")} →
        </button>
      ) : null}
    </div>
  );
}
