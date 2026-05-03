"use client";

import { useEffect, useMemo, useState } from "react";
import { useT } from "./i18n/I18nProvider";
import { Card } from "./ui";
import { getToken } from "../../lib/api";

const FIRST_IMPRESSION_KEY = "neyra:first_impression_seen_v1" as const;

export function FirstImpressionIntro({ variant = "default" }: { variant?: "default" | "compact" }) {
  const { t, locale } = useT("FirstImpressionIntro");
  const [visible, setVisible] = useState(false);

  const authed = useMemo(() => {
    try {
      return Boolean(getToken());
    } catch {
      return false;
    }
  }, []);

  useEffect(() => {
    if (!authed) return;
    try {
      const seen = localStorage.getItem(FIRST_IMPRESSION_KEY);
      if (seen === "1") return;
    } catch {
      // ignore
    }
    setVisible(true);
  }, [authed]);

  if (!authed) return null;
  if (!visible) return null;

  const items = [
    { id: "ai", title: t("onboarding.intro.ai_title"), body: t("onboarding.intro.ai_desc") },
    { id: "smart", title: t("onboarding.intro.smart_title"), body: t("onboarding.intro.smart_desc") },
    { id: "real", title: t("onboarding.intro.real_title"), body: t("onboarding.intro.real_desc") },
  ];

  return (
    <Card className="surface" key={locale} style={{ padding: variant === "compact" ? 14 : 16 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <div className="section-label">{t("onboarding.intro.eyebrow")}</div>
          <div className="h2" style={{ fontSize: variant === "compact" ? 18 : 20, fontWeight: 950, letterSpacing: "-0.03em", marginTop: 6 }}>
            {t("onboarding.intro.title")}
          </div>
          <div className="subtitle" style={{ marginTop: 6, opacity: 0.84, lineHeight: 1.35 }}>
            {t("onboarding.intro.subtitle")}
          </div>
        </div>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => {
            try {
              localStorage.setItem(FIRST_IMPRESSION_KEY, "1");
            } catch {
              // ignore
            }
            setVisible(false);
          }}
          style={{ padding: "6px 10px", borderRadius: 999, whiteSpace: "nowrap" }}
        >
          {t("onboarding.intro.dismiss")}
        </button>
      </div>

      <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
        {items.map((it) => (
          <div
            key={it.id}
            style={{
              padding: "10px 12px",
              borderRadius: 14,
              border: "1px solid rgba(255,255,255,0.12)",
              background: "rgba(255,255,255,0.05)",
            }}
          >
            <div style={{ fontWeight: 900 }}>{it.title}</div>
            <div className="caption" style={{ marginTop: 4, opacity: 0.86 }}>
              {it.body}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

