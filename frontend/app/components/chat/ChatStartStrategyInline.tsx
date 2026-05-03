"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { fetchStartStrategy, postAiMemoryEvent, postStartStrategyEvent } from "../../../lib/chat/api";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { useT } from "../../components/i18n/I18nProvider";

type Props = {
  viewerUserId: number | null;
  partnerUserId: number | null;
  messages: { content?: string; text?: string; role?: string }[];
  draft: string;
  disabled?: boolean;
  onMeta?: (meta: { lastInsertedText: string; lastInsertedStyle: string }) => void;
  onInsertDraft: (text: string, meta: { style: "light" | "flirty" | "curious" }) => void;
};

export function ChatStartStrategyInline({ viewerUserId, partnerUserId, messages, draft, disabled = false, onMeta, onInsertDraft }: Props) {
  const { t } = useT("ChatStartStrategyInline");
  const messageCount = (messages || []).length;
  const show = Boolean(partnerUserId && messageCount <= 2);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any | null>(null);
  const shownOnceRef = useRef(false);

  const contextMessages = useMemo(() => {
    const texts: string[] = [];
    for (const m of (messages || []).slice(-2)) {
      const t = String((m as any)?.content ?? (m as any)?.text ?? "").trim();
      if (t) texts.push(t);
    }
    return texts.slice(0, 3);
  }, [messages]);

  useEffect(() => {
    if (!show || disabled) return;
    if (shownOnceRef.current) return;
    shownOnceRef.current = true;
    setLoading(true);
    void (async () => {
      try {
        const res = await fetchStartStrategy({ partnerUserId: Number(partnerUserId), messages: contextMessages });
        setData(res);
        void trackAnalyticsEvent("ai_start_strategy_shown", { partner_user_id: partnerUserId, message_count: messageCount });
        if (partnerUserId) void postStartStrategyEvent({ name: "opener_shown", partner_user_id: Number(partnerUserId) }).catch(() => {});
        if (partnerUserId)
          void postAiMemoryEvent({
            event_type: "option_shown",
            partner_user_id: Number(partnerUserId),
            metadata_json: { source: "start_strategy" },
          }).catch(() => {});
      } catch {
        setData(null);
      } finally {
        setLoading(false);
      }
    })();
  }, [contextMessages, disabled, messageCount, partnerUserId, show]);

  if (!show) return null;
  if (loading) {
    return (
      <div className="chat-ai-replies" style={{ marginBottom: 10 }}>
        <div className="chat-ai-replies__label">{t("chat.ai.startStrategy.panelLabel")}</div>
        <div className="chat-ai-replies__row">
          <div className="chat-ai-replies__skeleton" />
          <div className="chat-ai-replies__skeleton" />
          <div className="chat-ai-replies__skeleton" />
        </div>
      </div>
    );
  }

  const openers: { style: "light" | "flirty" | "curious"; text: string }[] = Array.isArray(data?.openers) ? data.openers : [];
  if (!openers.length) return null;

  return (
    <div className="chat-ai-replies" style={{ marginBottom: 10 }}>
      <div className="chat-ai-replies__label">{t("chat.ai.startStrategy.panelLabel")}</div>
      {data?.strategy ? (
        <div className="caption" style={{ opacity: 0.9, marginBottom: 8 }}>
          <strong>{t("chat.startStrategy.title")}</strong> {String(data.strategy)}
          {Number.isFinite(Number(data?.confidence)) ? (
            <span style={{ opacity: 0.85 }}>
              {t("chat.ai.startStrategy.confidenceSuffix", {
                pct: Math.max(0, Math.min(100, Math.trunc(Number(data.confidence)))),
              })}
            </span>
          ) : null}
        </div>
      ) : null}

      <div className="chat-ai-replies__row">
        {openers.slice(0, 3).map((o, idx) => {
          const label =
            o.style === "flirty"
              ? t("chat.startStrategy.tone.flirty")
              : o.style === "curious"
                ? t("chat.startStrategy.tone.curious")
                : t("chat.startStrategy.tone.light");
          return (
            <button
              key={`${idx}:${o.style}:${o.text}`}
              type="button"
              className="chat-ai-replies__option"
              disabled={disabled}
              onClick={() => {
                const cleaned = String(o.text || "").trim();
                if (!cleaned) return;
                onMeta?.({ lastInsertedText: cleaned, lastInsertedStyle: o.style });
                void trackAnalyticsEvent("ai_start_opener_selected", { style: o.style, option_index: idx, partner_user_id: partnerUserId, viewer_user_id: viewerUserId ?? null });
                if (partnerUserId)
                  void postStartStrategyEvent({ name: "opener_selected", partner_user_id: Number(partnerUserId), style: o.style }).catch(() => {});
                if (partnerUserId)
                  void postAiMemoryEvent({
                    event_type: "option_selected",
                    partner_user_id: Number(partnerUserId),
                    metadata_json: { style: o.style, option_index: idx, nudge_type: "now", source: "start_strategy" },
                  }).catch(() => {});
                onInsertDraft(cleaned, { style: o.style });
              }}
            >
              <div className="chat-ai-replies__text">
                <div style={{ fontWeight: 900, marginBottom: 6 }}>{label}</div>
                <div>{o.text}</div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

