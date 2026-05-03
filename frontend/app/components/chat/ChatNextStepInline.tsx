"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage } from "../../../lib/chat/types";
import { fetchNextStep, fetchTimingDecision, type NextStepOption } from "../../../lib/chat/api";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { useT } from "../i18n/I18nProvider";
import { Button } from "../ui";

type Props = {
  partnerUserId: number | null;
  viewerUserId: number | null;
  messages: ChatMessage[];
  disabled?: boolean;
  onSendText: (text: string) => Promise<{ ok: true } | { ok: false } | undefined>;
  onOpenOtherOptions?: () => void;
};

function shownKey(partnerUserId: number, bucket: string): string {
  return `neyra:next_step_shown:${partnerUserId}:${bucket}`;
}

function computeAvgReplyMinutes(messages: ChatMessage[], viewerUserId: number, partnerUserId: number): number | null {
  // Rough: average time from partner -> viewer reply.
  const pairs: number[] = [];
  for (let i = 1; i < messages.length; i++) {
    const prev = messages[i - 1]!;
    const cur = messages[i]!;
    if (Number(prev.senderId) !== Number(partnerUserId)) continue;
    if (Number(cur.senderId) !== Number(viewerUserId)) continue;
    const t0 = Date.parse(String(prev.timestamp ?? prev.createdAt ?? "").trim());
    const t1 = Date.parse(String(cur.timestamp ?? cur.createdAt ?? "").trim());
    if (!Number.isFinite(t0) || !Number.isFinite(t1)) continue;
    const min = Math.max(0, Math.round((t1 - t0) / 60000));
    if (min > 0 && min <= 24 * 60) pairs.push(min);
  }
  if (!pairs.length) return null;
  const avg = pairs.reduce((a, b) => a + b, 0) / pairs.length;
  return Number.isFinite(avg) ? avg : null;
}

export function ChatNextStepInline({ partnerUserId, viewerUserId, messages, disabled = false, onSendText, onOpenOtherOptions }: Props) {
  const { t } = useT("ChatNextStepInline");
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<NextStepOption[]>([]);
  const [selected, setSelected] = useState(0);
  const [loading, setLoading] = useState(false);
  const lastDecisionRef = useRef<string>("");

  const last = useMemo(() => (messages && messages.length ? messages[messages.length - 1] : null), [messages]);
  const lastIso = useMemo(() => {
    const ts = last ? String(last.timestamp ?? last.createdAt ?? "").trim() : "";
    return ts || null;
  }, [last]);

  const whoSentLast = useMemo(() => {
    if (!last || viewerUserId == null || partnerUserId == null) return null;
    return Number(last.senderId) === Number(viewerUserId) ? ("me" as const) : Number(last.senderId) === Number(partnerUserId) ? ("them" as const) : null;
  }, [last, partnerUserId, viewerUserId]);

  const messageCount = messages?.length ?? 0;
  const conversationLength = messageCount;

  const replyTimeAvg = useMemo(() => {
    if (!viewerUserId || !partnerUserId) return null;
    return computeAvgReplyMinutes(messages || [], viewerUserId, partnerUserId);
  }, [messages, partnerUserId, viewerUserId]);

  const shouldConsider = Boolean(partnerUserId && viewerUserId && messageCount >= 6 && lastIso);

  const run = useCallback(async () => {
    if (!partnerUserId || !viewerUserId) return;
    if (!shouldConsider) return;

    const decisionRes = await fetchTimingDecision({
      partnerUserId,
      // Metrics-only contract (no message bodies).
      messages: [],
      lastMessageAt: lastIso,
      messageCount,
      replyTimeAvg,
      whoSentLast,
      conversationLength,
      interestStage: null,
      mutualityScore: null,
      stallScore: null,
    });
    if (!decisionRes) return;

    const decision = decisionRes.decision || (decisionRes.nudge_type === "revive" ? "revive" : decisionRes.nudge_type === "now" ? "now" : "wait");
    lastDecisionRef.current = decision;

    if (decision !== "now" && decision !== "escalate") {
      setOpen(false);
      return;
    }

    // Anti-spam: at most once per 6h per decision bucket.
    const bucket = decision;
    try {
      const prev = Number(sessionStorage.getItem(shownKey(partnerUserId, bucket)) || 0);
      if (Number.isFinite(prev) && prev > 0 && Date.now() - prev < 6 * 60 * 60 * 1000) return;
      sessionStorage.setItem(shownKey(partnerUserId, bucket), String(Date.now()));
    } catch {
      /* ignore */
    }

    setLoading(true);
    try {
      const opts = await fetchNextStep();
      if (!opts.length) return;
      setOptions(opts);
      // Pick “best” based on decision.
      const best =
        decision === "escalate"
          ? Math.max(0, opts.findIndex((o) => o.type === "date"))
          : Math.max(0, opts.findIndex((o) => o.type === "voice"));
      setSelected(best >= 0 ? best : 0);
      // Fade-in after last message (not intrusive).
      window.setTimeout(() => setOpen(true), 650);
      void trackAnalyticsEvent("ai_next_step_shown", { partner_user_id: partnerUserId, decision });
    } finally {
      setLoading(false);
    }
  }, [conversationLength, lastIso, messageCount, partnerUserId, replyTimeAvg, shouldConsider, viewerUserId, whoSentLast]);

  useEffect(() => {
    setOpen(false);
    if (!shouldConsider) return;
    const tmr = window.setTimeout(() => void run(), 900);
    return () => window.clearTimeout(tmr);
  }, [run, shouldConsider, lastIso]);

  const active = options[selected] ?? null;
  if (!partnerUserId || !viewerUserId) return null;
  if (!shouldConsider) return null;
  if (!open && !loading) return null;

  return (
    <div className={["chat-next-step", open ? "chat-next-step--in" : ""].filter(Boolean).join(" ")}>
      <div className="chat-next-step__title">{t("chat.nextStep.title")}</div>
      {active ? <div className="chat-next-step__text">{active.text}</div> : null}
      <div className="chat-next-step__actions">
        <Button
          type="button"
          variant="primary"
          disabled={disabled || !active}
          className="chat-next-step__sendPulse"
          onClick={() => {
            if (!active) return;
            void trackAnalyticsEvent("ai_next_step_send_clicked", { partner_user_id: partnerUserId, type: active.type });
            void onSendText(active.text);
          }}
        >
          {t("chat.nextStep.sendSuggestion")}
        </Button>
        <Button type="button" variant="secondary" disabled={disabled || options.length < 2} onClick={() => onOpenOtherOptions?.()}>
          {t("chat.nextStep.otherOptions")}
        </Button>
      </div>

      {options.length > 1 ? (
        <div className="chat-next-step__chips" role="list">
          {options.map((o, idx) => (
            <button
              key={`${o.type}-${idx}`}
              type="button"
              className={["chat-next-step__chip", idx === selected ? "chat-next-step__chip--selected" : ""].filter(Boolean).join(" ")}
              onClick={() => setSelected(idx)}
              disabled={disabled}
            >
              {o.type === "voice" ? t("chat.nextStep.type.voice") : o.type === "date" ? t("chat.nextStep.type.date") : t("chat.nextStep.type.video")}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

