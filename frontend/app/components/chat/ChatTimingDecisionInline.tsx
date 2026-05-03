"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { fetchTimingDecision } from "../../../lib/chat/api";
import type { ChatMessage } from "../../../lib/chat/types";
import { useT } from "../../components/i18n/I18nProvider";

type Timing = {
  should_send_now: boolean;
  confidence: number;
  nudge_type: "now" | "wait" | "reengage" | "revive";
  best_time_window: string;
  reasoning: string;
};

type Props = {
  partnerUserId: number | null;
  viewerUserId: number | null;
  messages: ChatMessage[];
  interestStage?: "cold" | "warming" | "engaged" | "ready" | null;
  mutualityScore?: number | null;
  stallScore?: number | null;
  onDecision?: (d: Timing | null) => void;
};

export function ChatTimingDecisionInline({
  partnerUserId,
  viewerUserId,
  messages,
  interestStage = null,
  mutualityScore = null,
  stallScore = null,
  onDecision,
}: Props) {
  const { t } = useT("ChatTimingDecisionInline");
  const [timing, setTiming] = useState<Timing | null>(null);
  const [loading, setLoading] = useState(false);
  const genRef = useRef(0);

  const ctx = useMemo(() => {
    const out: { role: "me" | "them"; text: string }[] = [];
    for (const m of (messages || []).slice(-50)) {
      const text = String(m.content || "").trim();
      if (!text) continue;
      const role: "me" | "them" = viewerUserId != null && Number(m.senderId) === Number(viewerUserId) ? "me" : "them";
      out.push({ role, text });
    }
    return out;
  }, [messages, viewerUserId]);

  useEffect(() => {
    if (!partnerUserId) return;
    if (messages.length === 0) {
      setTiming(null);
      onDecision?.(null);
      setLoading(false);
      return;
    }
    const gen = (genRef.current += 1);
    setLoading(true);
    void (async () => {
      try {
        const res = await fetchTimingDecision({
          partnerUserId,
          messages: ctx,
          interestStage,
          mutualityScore,
          stallScore,
        });
        if (genRef.current !== gen) return;
        const next = res ? (res as any) : null;
        setTiming(next);
        onDecision?.(next);
      } finally {
        if (genRef.current === gen) setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onDecision is optional notify; stable enough for timing
  }, [ctx, interestStage, mutualityScore, messages.length, partnerUserId, stallScore]);

  if (!partnerUserId) return null;
  if (messages.length === 0) return null;
  if (loading && !timing) return null;
  if (!timing) return null;

  const title =
    timing.nudge_type === "now"
      ? t("chat.startStrategy.timing.titleNow")
      : timing.nudge_type === "reengage"
        ? t("chat.startStrategy.timing.titleReengage")
        : timing.nudge_type === "revive"
          ? t("chat.startStrategy.timing.titleRevive")
          : t("chat.startStrategy.betterWait");

  return (
    <div style={{ marginBottom: 10 }}>
      <div
        style={{
          padding: "10px 12px",
          borderRadius: 14,
          border: "1px solid rgba(255, 255, 255, 0.10)",
          background: "rgba(255, 255, 255, 0.04)",
          display: "grid",
          gap: 6,
        }}
      >
        <div style={{ fontWeight: 900 }}>{title}</div>
        {timing.reasoning ? (
          <div className="caption" style={{ opacity: 0.9 }}>
            {timing.reasoning}
          </div>
        ) : null}
        {timing.nudge_type === "wait" && timing.best_time_window ? (
          <div className="caption" style={{ opacity: 0.85 }}>
            <strong>{t("chat.startStrategy.bestWindow")}</strong> {timing.best_time_window}
          </div>
        ) : null}
      </div>
    </div>
  );
}

