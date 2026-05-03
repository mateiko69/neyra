"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef } from "react";
import type { ChatMessage } from "../../../lib/chat/types";
import type { AiTier } from "../../../lib/chat/aiTier";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { useT } from "../i18n/I18nProvider";

type Props = {
  messages: ChatMessage[];
  viewerUserId: number | null;
  partnerUserId: number | null;
  composerDraft?: string;
  aiTier: AiTier;
  disabled?: boolean;
  onOpenAi?: () => void;
};

export function ChatMomentumDateCoach({
  messages,
  viewerUserId,
  partnerUserId,
  composerDraft = "",
  aiTier,
  disabled = false,
  onOpenAi,
}: Props) {
  const { t } = useT("ChatMomentumDateCoach");
  const shownRef = useRef(false);

  const meaningfulCount = useMemo(() => {
    return (messages || []).filter((m) => String(m?.content || "").trim().length > 0).length;
  }, [messages]);

  const draftBusy = Boolean(String(composerDraft || "").trim());
  const show =
    !disabled &&
    partnerUserId != null &&
    viewerUserId != null &&
    !draftBusy &&
    meaningfulCount >= 2 &&
    meaningfulCount <= 18;

  useEffect(() => {
    if (!show || shownRef.current) return;
    shownRef.current = true;
    void trackAnalyticsEvent("chat_momentum_coach_shown", { tier: aiTier, messages: meaningfulCount });
  }, [show, aiTier, meaningfulCount]);

  if (!show) return null;

  return (
    <div
      className="surface"
      style={{
        marginTop: 2,
        padding: "12px 14px",
        borderRadius: 16,
        border: "1px solid rgba(124, 92, 255, 0.28)",
        background: "linear-gradient(145deg, rgba(124, 92, 255, 0.12), rgba(79, 140, 255, 0.06))",
        lineHeight: 1.45,
      }}
      aria-live="polite"
    >
      <div style={{ fontWeight: 850, fontSize: 14, letterSpacing: "-0.02em" }}>{t("chat.momentum.title")}</div>
      <div className="caption" style={{ marginTop: 6, opacity: 0.9 }}>
        {t("chat.momentum.body")}
      </div>
      <div className="caption" style={{ marginTop: 8, opacity: 0.78, fontStyle: "italic" }}>
        {t("chat.momentum.emotional")}
      </div>
      <div style={{ marginTop: 10, display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
        {aiTier === "free" ? (
          <Link
            href="/premium?source=chat_momentum_coach"
            className="btn btn-primary"
            style={{ fontSize: 14, padding: "8px 14px" }}
            onClick={() => void trackAnalyticsEvent("paywall_clicked", { surface: "chat_momentum_date_coach", tier: aiTier })}
          >
            {t("chat.momentum.ctaUpgrade")}
          </Link>
        ) : (
          <button
            type="button"
            className="btn btn-primary"
            style={{ fontSize: 14, padding: "8px 14px" }}
            onClick={() => {
              void trackAnalyticsEvent("paywall_clicked", { surface: "chat_momentum_date_coach", tier: aiTier, action: "open_ai" });
              onOpenAi?.();
            }}
          >
            {t("chat.momentum.ctaAi")}
          </button>
        )}
      </div>
    </div>
  );
}
