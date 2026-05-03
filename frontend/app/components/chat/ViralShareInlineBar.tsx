"use client";

import { useT } from "../i18n/I18nProvider";
import { trackAnalyticsEvent } from "../../../lib/analytics";

type Props = {
  onShare: () => void;
  onDismiss: () => void;
};

/**
 * Non-blocking inline prompt after a strong AI send — not a full-screen gate.
 */
export function ViralShareInlineBar({ onShare, onDismiss }: Props) {
  const { t } = useT("ViralShareInlineBar");

  return (
    <div
      className="viral-share-inline surface"
      role="status"
      style={{
        margin: "0 18px 10px",
        padding: "12px 14px",
        borderRadius: 14,
        border: "1px solid rgba(124, 92, 255, 0.22)",
        background: "linear-gradient(145deg, rgba(124, 92, 255, 0.1), rgba(20, 24, 36, 0.55))",
        display: "grid",
        gap: 8,
        maxWidth: "min(100%, 560px)",
      }}
    >
      <div className="caption" style={{ opacity: 0.92, lineHeight: 1.4, fontWeight: 650 }}>
        {t("viral.inline.prompt")}
      </div>
      <div className="caption" style={{ opacity: 0.72, lineHeight: 1.35, fontSize: 13 }}>
        {t("viral.inline.referralHint")}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        <button type="button" className="btn btn-primary" onClick={onShare}>
          {t("viral.inline.shareCta")}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onDismiss}>
          {t("viral.inline.dismiss")}
        </button>
      </div>
    </div>
  );
}

export function trackViralShareClicked(surface: string): void {
  void trackAnalyticsEvent("share_clicked", { surface });
}
