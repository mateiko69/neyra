"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage } from "../../../lib/chat/types";
import type { AiTier } from "../../../lib/chat/aiTier";
import { fetchTimedReplies, type AiLanguageToneContext, type TimedReplyOption } from "../../../lib/chat/api";
import { consumeDailyBoost } from "../../../lib/dailyBoosts";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { neyraAiLocaleDevLog } from "../../../lib/chat/neyraAiLocaleLog";
import { useT } from "../i18n/I18nProvider";
import { getChatFallbackPack } from "../../../lib/ai/chatFallbackReplies";
import { ApiPaywallError } from "../../../lib/api";
import { Button } from "../ui";

const TWENTY_FOUR_H_MS = 24 * 60 * 60 * 1000;
const FORTY_EIGHT_H_MS = 48 * 60 * 60 * 1000;

type Props = {
  partnerUserId: number | null;
  viewerUserId: number | null;
  messages: ChatMessage[];
  composerDraft?: string;
  disabled?: boolean;
  aiCtx?: AiLanguageToneContext;
  aiTier?: AiTier;
  onInsert: (text: string, meta: { style: TimedReplyOption["style"]; index: number }) => void;
};

function messageTimeMs(m: ChatMessage): number {
  const anyM = m as any;
  const raw = anyM.timestamp ?? anyM.createdAt ?? anyM.created_at ?? null;
  const ms = typeof raw === "number" ? raw : Date.parse(String(raw || ""));
  return Number.isFinite(ms) ? ms : 0;
}

/** No reply from match after viewer sent the last message — 24h+ (product spec). */
export function computeNoReplyReviveTier(
  messages: ChatMessage[],
  viewerUserId: number,
  partnerUserId: number,
): "revive" | "strong" | null {
  const safe = messages || [];
  if (safe.length < 1) return null;
  const last = safe[safe.length - 1];
  if (!last) return null;
  if (Number(last.senderId) !== Number(viewerUserId)) return null;
  const lastMs = messageTimeMs(last);
  if (!lastMs) return null;
  const age = Date.now() - lastMs;
  if (age < TWENTY_FOUR_H_MS) return null;
  return age >= FORTY_EIGHT_H_MS ? "strong" : "revive";
}

export function ChatReviveSuggestionsInline({
  partnerUserId,
  viewerUserId,
  messages,
  composerDraft = "",
  disabled = false,
  aiCtx,
  aiTier = "premium",
  onInsert,
}: Props) {
  const { t, locale: uiLocaleTag } = useT("ChatReviveSuggestionsInline");
  const pack = useMemo(() => getChatFallbackPack(uiLocaleTag), [uiLocaleTag]);
  const [options, setOptions] = useState<TimedReplyOption[]>([]);
  const [dailyLimitHint, setDailyLimitHint] = useState(false);
  const [choiceFeedback, setChoiceFeedback] = useState(false);
  const lastFetchKeyRef = useRef<string>("");
  const trackedShownRef = useRef<string>("");

  const noReplyTier = useMemo(() => {
    if (!viewerUserId || !partnerUserId) return null;
    return computeNoReplyReviveTier(messages, viewerUserId, partnerUserId);
  }, [messages, partnerUserId, viewerUserId]);

  const ctx = useMemo(() => {
    if (!viewerUserId) return [];
    const out: { role: "me" | "them"; text: string }[] = [];
    for (const m of (messages || []).slice(-30)) {
      const text = String((m as any).content || "").trim();
      if (!text) continue;
      const role: "me" | "them" = Number((m as any).senderId) === Number(viewerUserId) ? "me" : "them";
      out.push({ role, text });
    }
    return out;
  }, [messages, viewerUserId]);

  const revivePlusEligible = aiTier === "premium_plus";

  useEffect(() => {
    lastFetchKeyRef.current = "";
    trackedShownRef.current = "";
    setDailyLimitHint(false);
  }, [partnerUserId, uiLocaleTag]);

  useEffect(() => {
    if (disabled || !partnerUserId || !viewerUserId) {
      setOptions([]);
      lastFetchKeyRef.current = "";
      trackedShownRef.current = "";
      return;
    }

    const draftBusy = Boolean(String(composerDraft || "").trim());
    if (draftBusy) return;

    const last = (messages || []).slice(-1)[0];
    const lastId = String((last as any)?.id ?? (last as any)?.rawId ?? "") || String(messageTimeMs(last as ChatMessage));
    const mode = noReplyTier ? `dead:${noReplyTier}` : "";
    if (!mode) {
      setOptions([]);
      lastFetchKeyRef.current = "";
      trackedShownRef.current = "";
      return;
    }
    const fetchKey = `${partnerUserId}:${lastId}:${uiLocaleTag}:${mode}`;
    if (lastFetchKeyRef.current === fetchKey) return;
    lastFetchKeyRef.current = fetchKey;

    if (noReplyTier === "strong") {
      setOptions([
        { style: "light", text: t("chat.noReply.strong.example") },
        { style: "flirty", text: t("chat.noReply.strong.alt1") },
        { style: "deep", text: t("chat.noReply.strong.alt2") },
      ]);
    } else {
      setOptions([
        { style: "light", text: t("chat.noReply.revive.example") },
        { style: "flirty", text: t("chat.noReply.revive.alt1") },
        { style: "deep", text: t("chat.noReply.revive.alt2") },
      ]);
    }

    if (trackedShownRef.current !== fetchKey) {
      trackedShownRef.current = fetchKey;
      if (!revivePlusEligible) {
        void trackAnalyticsEvent("paywall_shown", {
          surface: "chat_revive_premium_plus_required",
          partner_user_id: partnerUserId,
          revive_tier: noReplyTier,
        });
      } else {
        void trackAnalyticsEvent("chat_no_reply_nudge_shown", { partner_user_id: partnerUserId, tier: noReplyTier });
        void trackAnalyticsEvent("reengagement_chat_revive_hint", { source: "chat", partner_user_id: partnerUserId, revive_tier: noReplyTier });
      }
    }

    if (!revivePlusEligible) {
      return;
    }

    const nudgeType = noReplyTier === "strong" ? "reengage" : "revive";
    neyraAiLocaleDevLog("requesting suggestions", { endpoint: "timed-replies", locale: uiLocaleTag, partnerUserId, nudgeType });
    void (async () => {
      try {
        const { options: timed } = await fetchTimedReplies({
          messages: ctx,
          nudgeType,
          interestStage: null,
          mutualityScore: null,
          aiCtx: { ...aiCtx, uiLocale: uiLocaleTag },
          partnerUserId,
        });
        if (timed.length) {
          neyraAiLocaleDevLog("received suggestions", { endpoint: "timed-replies", locale: uiLocaleTag, partnerUserId, nudgeType });
          setOptions(timed.slice(0, 3));
          setDailyLimitHint(false);
        }
      } catch (e: unknown) {
        if (e instanceof ApiPaywallError) {
          setDailyLimitHint(true);
          void trackAnalyticsEvent("paywall_shown", { surface: "chat_revive_daily_limit" });
        }
      }
    })();
  }, [
    aiCtx,
    revivePlusEligible,
    composerDraft,
    ctx,
    disabled,
    messages,
    partnerUserId,
    noReplyTier,
    viewerUserId,
    uiLocaleTag,
  ]); /* eslint-disable-line react-hooks/exhaustive-deps -- `t()` only seeds static fallback rows tied to fetchKey. */

  const draftBusy = Boolean(String(composerDraft || "").trim());
  if (disabled || draftBusy) return null;
  if (!noReplyTier) return null;

  if (!revivePlusEligible) {
    return (
      <div
        className="chat-first-opener chat-first-opener--in surface chat-brain-panel__simple-card--soft-mon"
        style={{ padding: "12px 14px", borderRadius: 14 }}
        aria-label={t("chat.reviveUpsell.aria")}
      >
        <div className="chat-first-opener__badge">{t("chat.reviveUpsell.badge")}</div>
        <div className="caption" style={{ marginTop: 6, opacity: 0.92, lineHeight: 1.4 }}>
          {t("chat.reviveUpsell.title")}
        </div>
        <div className="caption" style={{ marginTop: 6, opacity: 0.78, lineHeight: 1.35, fontStyle: "italic" }}>
          {t("chat.reviveUpsell.subtitle")}
        </div>
        <div className="caption" style={{ marginTop: 8, opacity: 0.85 }}>
          {t("chat.softMon.revivePricingLine")}
        </div>
        <div style={{ marginTop: 12 }}>
          <a
            className="btn btn-primary"
            href="/premium?source=chat_revive_premium_plus"
            onClick={() =>
              void trackAnalyticsEvent("paywall_clicked", {
                surface: "chat_revive_premium_plus_inline",
                cta_label: "continue",
              })
            }
          >
            {t("chat.softMon.ctaContinue")}
          </a>
        </div>
      </div>
    );
  }

  if (!options.length) return null;

  const badge = noReplyTier === "strong" ? t("chat.noReply.strong.title") : t("chat.noReply.revive.title");
  const subtitle = noReplyTier === "strong" ? t("chat.noReply.strong.subtitle") : t("chat.noReply.revive.subtitle");

  return (
    <div className="chat-first-opener chat-first-opener--in" aria-label={t("chat.revive.aria")}>
      <div className="chat-first-opener__badge">{badge}</div>
      <div className="caption" style={{ marginTop: 6, opacity: 0.88, lineHeight: 1.35 }}>
        {subtitle}
      </div>
      <div className="caption" style={{ marginTop: 4, opacity: 0.78, lineHeight: 1.35 }}>
        {t("retention.chat.sendQuick")}
      </div>
      {dailyLimitHint ? (
        <div
          className="surface chat-brain-panel__simple-card--soft-mon"
          style={{ marginTop: 10, padding: "10px 12px", borderRadius: 12 }}
          role="status"
        >
          <div className="caption" style={{ opacity: 0.9, lineHeight: 1.35 }}>
            {t("chat.softMon.limitInlineHint")}
          </div>
          <div style={{ marginTop: 10 }}>
            <a
              className="btn btn-primary"
              href="/premium?source=chat_revive_daily_limit"
              onClick={() =>
                void trackAnalyticsEvent("paywall_clicked", {
                  surface: "chat_revive_daily_limit_inline",
                  cta_label: "continue",
                })
              }
            >
              {t("chat.softMon.ctaContinue")}
            </a>
          </div>
        </div>
      ) : null}
      <div className="chat-first-opener__options" role="list" style={{ marginTop: 10 }}>
        {options.slice(0, 3).map((o, idx) => (
          <button
            key={`${o.style}-${idx}:${o.text.slice(0, 24)}`}
            type="button"
            className="chat-first-opener__option chat-first-opener__option--selected"
            disabled={disabled}
            onClick={() => {
              void consumeDailyBoost("revive");
              void trackAnalyticsEvent("revive_used", { partner_user_id: partnerUserId, style: o.style, index: idx });
              void trackAnalyticsEvent("ai_used", { surface: "chat_revive_suggestion", partner_user_id: partnerUserId, index: idx });
              void trackAnalyticsEvent("ai_used_after_pay", {
                surface: "chat_revive_suggestion",
                partner_user_id: partnerUserId,
                index: idx,
              });
              setChoiceFeedback(true);
              window.setTimeout(() => setChoiceFeedback(false), 1400);
              onInsert(o.text, { style: o.style, index: idx });
            }}
          >
            <div className="chat-first-opener__option-type">
              {o.style === "light" ? pack.easyLabel : o.style === "flirty" ? pack.flirtyLabel : pack.deepLabel}
            </div>
            <div className="chat-first-opener__option-text">{o.text}</div>
          </button>
        ))}
      </div>
      {choiceFeedback ? (
        <div className="caption text-white/70" style={{ marginTop: 8 }}>
          {"Nice choice 😉"}
        </div>
      ) : null}
    </div>
  );
}
