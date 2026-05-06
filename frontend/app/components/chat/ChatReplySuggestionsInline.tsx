"use client";

import Link from "next/link";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage } from "../../../lib/chat/types";
import type { AiTier } from "../../../lib/chat/aiTier";
import { fetchTimedReplies, type TimedReplyOption } from "../../../lib/chat/api";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import type { AiLanguageToneContext } from "../../../lib/chat/api";
import { neyraAiLocaleDevLog, neyraAiLocaleRenderedSuggestions } from "../../../lib/chat/neyraAiLocaleLog";
import { useT } from "../i18n/I18nProvider";
import { fetchDailyBoosts } from "../../../lib/dailyBoosts";
import { getChatFallbackPack, styleMetaFromPack, timedReplyFallbackTriplet } from "../../../lib/ai/chatFallbackReplies";
import { ApiPaywallError } from "../../../lib/api";
import { bumpAiUsageMoment } from "../../../lib/monetization/valueMoments";

type Props = {
  partnerUserId: number | null;
  viewerUserId: number | null;
  messages: ChatMessage[];
  /** Hide chips while the user has text in the composer (typing). */
  composerDraft?: string;
  disabled?: boolean;
  aiTier?: AiTier;
  aiCtx?: AiLanguageToneContext;
  onInsert: (text: string, meta: { style: TimedReplyOption["style"]; index: number }) => void;
};

export function ChatReplySuggestionsInline({
  partnerUserId,
  viewerUserId,
  messages,
  composerDraft = "",
  disabled = false,
  aiTier = "premium",
  aiCtx,
  onInsert,
}: Props) {
  const { t, locale: uiLocaleTag } = useT("ChatReplySuggestionsInline");
  const isFreeTier = aiTier === "free";
  const isPlusTier = aiTier === "premium_plus";
  const suggestCap = isFreeTier ? 1 : 3;
  const pack = useMemo(() => getChatFallbackPack(uiLocaleTag), [uiLocaleTag]);
  const [options, setOptions] = useState<TimedReplyOption[]>([]);
  const [open, setOpen] = useState(false);
  const [limited, setLimited] = useState(false);
  const [waitingAi, setWaitingAi] = useState(false);
  const [hardFreeLimit, setHardFreeLimit] = useState(false);
  const [choiceFeedback, setChoiceFeedback] = useState(false);
  const paywallShownForIncomingRef = useRef<string>("");
  const aiLimitHitForIncomingRef = useRef<string>("");
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const lastIncomingIdRef = useRef<string>("");
  const selectAnimTimerRef = useRef<number | null>(null);
  const sourceRef = useRef<"ai" | "fallback">("fallback");
  const requestSeqRef = useRef(0);
  const applyOptionsTimerRef = useRef<number | null>(null);
  const waitingTimerRef = useRef<number | null>(null);

  const draftTrim = String(composerDraft ?? "").trim();
  const lockedPreview = useMemo(() => timedReplyFallbackTriplet(pack).slice(0, 3), [pack]);

  const lastIncoming = useMemo(() => {
    if (!partnerUserId) return null;
    const last = (messages || []).slice(-1)[0] ?? null;
    if (!last) return null;
    if (Number(last.senderId) !== Number(partnerUserId)) return null;
    const text = String(last.content || "").trim();
    if (!text) return null;
    return last;
  }, [messages, partnerUserId]);
  const ctx = useMemo(() => {
    if (!viewerUserId) return [];
    const out: { role: "me" | "them"; text: string }[] = [];
    for (const m of (messages || []).slice(-30)) {
      const text = String(m.content || "").trim();
      if (!text) continue;
      const role: "me" | "them" = Number(m.senderId) === Number(viewerUserId) ? "me" : "them";
      out.push({ role, text });
    }
    return out;
  }, [messages, viewerUserId]);

  useLayoutEffect(() => {
    requestSeqRef.current += 1;
    if (applyOptionsTimerRef.current != null) {
      window.clearTimeout(applyOptionsTimerRef.current);
      applyOptionsTimerRef.current = null;
    }
    if (waitingTimerRef.current != null) {
      window.clearTimeout(waitingTimerRef.current);
      waitingTimerRef.current = null;
    }
    setOptions([]);
    setOpen(false);
    setWaitingAi(false);
    lastIncomingIdRef.current = "";
  }, [aiCtx?.overrideLanguage, uiLocaleTag]);

  useEffect(() => {
    lastIncomingIdRef.current = "";
  }, [partnerUserId]);

  useEffect(() => {
    if (!partnerUserId || !viewerUserId) {
      setOpen(false);
      setOptions([]);
      setLimited(false);
      setWaitingAi(false);
      return;
    }
    if ((messages || []).length < 1) {
      setOpen(false);
      setOptions([]);
      setWaitingAi(false);
      return;
    }
    if (!lastIncoming) {
      setOpen(false);
      setOptions([]);
      setWaitingAi(false);
      return;
    }

    const incomingId = String(lastIncoming.rawId ?? lastIncoming.id ?? lastIncoming.createdAt ?? "");
    if (!incomingId) return;
    if (lastIncomingIdRef.current === incomingId) return;
    lastIncomingIdRef.current = incomingId;
    setLimited(false);
    sourceRef.current = "fallback";

    const fb = timedReplyFallbackTriplet(pack);
    setOptions(isFreeTier ? fb.slice(0, 1) : fb.slice(0, 3));
    setOpen(true);
    setWaitingAi(true);

    const aiRequestCtx: AiLanguageToneContext = { ...(aiCtx ?? {}), uiLocale: uiLocaleTag };
    neyraAiLocaleDevLog("requesting suggestions", { endpoint: "timed-replies", locale: uiLocaleTag, partnerUserId, nudgeType: "now" });

    void (async () => {
      const requestSeq = ++requestSeqRef.current;
      const localeAtStart = uiLocaleTag;
      try {
        const daily = await fetchDailyBoosts();
        if (isFreeTier && daily && (daily.reply_remaining ?? 0) < 1) {
          setLimited(true);
          setOptions(lockedPreview);
          setWaitingAi(false);
          neyraAiLocaleRenderedSuggestions({ locale: uiLocaleTag, source: "fallback_quota" });
          if (aiLimitHitForIncomingRef.current !== incomingId) {
            aiLimitHitForIncomingRef.current = incomingId;
            void trackAnalyticsEvent("ai_limit_hit", { surface: "timed_reply_daily_cap", partner_user_id: partnerUserId });
          }
          return;
        }
        const { options: timed, source: trSource } = await fetchTimedReplies({
          messages: ctx,
          nudgeType: "now",
          interestStage: null,
          mutualityScore: null,
          aiCtx: aiRequestCtx,
          partnerUserId,
        });
        if (isFreeTier && trSource === "fallback_quota") {
          setLimited(true);
          setOptions(lockedPreview);
          setWaitingAi(false);
          neyraAiLocaleRenderedSuggestions({ locale: uiLocaleTag, source: "fallback_quota" });
          if (aiLimitHitForIncomingRef.current !== incomingId) {
            aiLimitHitForIncomingRef.current = incomingId;
            void trackAnalyticsEvent("ai_limit_hit", { surface: "timed_reply_api_quota", partner_user_id: partnerUserId });
          }
          return;
        }
        if (timed.length) {
          sourceRef.current = trSource === "ai" ? "ai" : "fallback";
          if (isFreeTier && trSource === "ai") bumpAiUsageMoment(1);
          neyraAiLocaleDevLog("received suggestions", { endpoint: "timed-replies", locale: uiLocaleTag, partnerUserId, nudgeType: "now" });
          const delayMs = 380 + Math.trunc(Math.random() * 520);
          applyOptionsTimerRef.current = window.setTimeout(() => {
            if (requestSeqRef.current !== requestSeq) return;
            if (localeAtStart !== uiLocaleTag) return;
            setOptions(timed.slice(0, suggestCap));
            neyraAiLocaleRenderedSuggestions({ locale: uiLocaleTag, source: trSource === "ai" ? "ai" : "fallback" });
            applyOptionsTimerRef.current = null;
          }, delayMs);
        } else {
          neyraAiLocaleRenderedSuggestions({ locale: uiLocaleTag, source: "fallback" });
        }
      } catch (e: unknown) {
        const em = String((e as any)?.message || "").toLowerCase();
        if (e instanceof ApiPaywallError || em.includes("limit_reached") || em.includes("free_limit_reached")) {
          setLimited(true);
          setOptions(lockedPreview);
          setHardFreeLimit(em.includes("free ai") || em.includes("free_limit_reached"));
          if (aiLimitHitForIncomingRef.current !== incomingId) {
            aiLimitHitForIncomingRef.current = incomingId;
            void trackAnalyticsEvent("ai_limit_hit", { surface: "timed_reply_paywall_error", partner_user_id: partnerUserId });
          }
          if (paywallShownForIncomingRef.current !== incomingId) {
            paywallShownForIncomingRef.current = incomingId;
            void trackAnalyticsEvent("paywall_shown", { surface: "timed_reply_limit_reached" });
          }
        }
        neyraAiLocaleRenderedSuggestions({ locale: uiLocaleTag, source: "fallback" });
      } finally {
        const delayMs = 520 + Math.trunc(Math.random() * 700);
        waitingTimerRef.current = window.setTimeout(() => {
          if (requestSeqRef.current !== requestSeq) return;
          if (localeAtStart !== uiLocaleTag) return;
          setWaitingAi(false);
          waitingTimerRef.current = null;
        }, delayMs);
      }
    })();
  }, [aiCtx, ctx, isFreeTier, lastIncoming, lockedPreview, pack, partnerUserId, suggestCap, uiLocaleTag, viewerUserId]);

  useEffect(() => {
    return () => {
      if (selectAnimTimerRef.current != null) window.clearTimeout(selectAnimTimerRef.current);
      if (applyOptionsTimerRef.current != null) window.clearTimeout(applyOptionsTimerRef.current);
      if (waitingTimerRef.current != null) window.clearTimeout(waitingTimerRef.current);
    };
  }, []);

  if (draftTrim.length > 0) return null;
  if (!open) return null;

  if (limited && options.length > 0) {
    return (
      <div className="chat-first-opener chat-first-opener--in chat-first-opener--under-message" aria-label={t("chat.reply.aria")}>
        <div className="chat-first-opener__badge">{t("chat.reply.title")}</div>
        <div className="chat-reply-premium-gate">
          <div className="chat-reply-premium-gate__blur" aria-hidden>
            <div className="chat-first-opener__options chat-first-opener__options--inline chat-reply-styles">
              {lockedPreview.map((o, idx) => {
                const meta = styleMetaFromPack(pack, o.style);
                return (
                  <div key={`blur-${o.style}-${idx}`} className="chat-reply-style">
                    <span className="chat-reply-style__label">{meta.label}</span>
                    <span className="chat-reply-style__text">{o.text}</span>
                    <span className="chat-reply-style__hint">{meta.hint}</span>
                  </div>
                );
              })}
            </div>
          </div>
          <div className="chat-reply-premium-gate__overlay" aria-live="polite">
            <div className="chat-reply-premium-gate__copy">
              <div className="chat-reply-premium-gate__title">{t("chat.ai.limit.unlockBlurTitle")}</div>
              <div className="caption" style={{ marginTop: 6, opacity: 0.88 }}>
                {t("chat.ai.limit.greatResponsesLine")}
              </div>
              <Link
                className="chat-reply-premium-gate__cta"
                href="/premium?source=premium_ai_replies"
                onClick={() => void trackAnalyticsEvent("paywall_clicked", { source: "ai_limit", surface: "timed_reply_quota_blur_gate" })}
              >
                {t("chat.softMon.ctaContinue")}
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (limited) {
    return (
      <div className="chat-first-opener chat-first-opener--in chat-first-opener--under-message" aria-label={t("chat.reply.aria")}>
        <div className="chat-first-opener__badge">{t("chat.reply.title")}</div>
        <div className="chat-ai-inline__upsell" aria-live="polite">
          <div className="chat-ai-inline__upsell-text">{t("chat.ai.limit.greatResponsesLine")}</div>
          <Link
            className="chat-ai-inline__upgrade"
            href="/premium?source=premium_ai_replies"
            onClick={() => void trackAnalyticsEvent("paywall_clicked", { source: "ai_limit", surface: "timed_reply_quota_empty" })}
          >
            {t("chat.softMon.ctaContinue")}
          </Link>
        </div>
      </div>
    );
  }

  if (!options.length) return null;

  return (
    <div className="chat-first-opener chat-first-opener--in chat-first-opener--under-message" aria-label={t("chat.reply.aria")}>
      {hardFreeLimit ? (
        <div
          className="chat-soft-mon-inline"
          role="note"
          style={{
            marginBottom: 10,
            padding: "10px 12px",
            borderRadius: 12,
            border: "1px solid rgba(124,92,255,0.28)",
            background: "linear-gradient(145deg, rgba(124,92,255,0.12), rgba(79,140,255,0.06))",
          }}
        >
          <div className="caption" style={{ marginBottom: 8, opacity: 0.9, lineHeight: 1.4 }}>
            {t("chat.softMon.limitInlineHint")}
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <Link
              className="btn btn-primary"
              href="/premium?source=free_limit_reached_reply"
              onClick={() => void trackAnalyticsEvent("paywall_clicked", { source: "ai_limit", surface: "free_limit_reached_reply" })}
            >
              {t("chat.softMon.ctaContinue")}
            </Link>
            <button type="button" className="btn btn-ghost" onClick={() => setHardFreeLimit(false)}>
              {t("common.dismiss")}
            </button>
          </div>
        </div>
      ) : null}
      <div className="chat-first-opener__badge">{t("chat.reply.inlineBadge")}</div>
      {waitingAi ? (
        <div className="caption" style={{ marginTop: 8, opacity: 0.85 }} aria-live="polite">
          {pack.inlineLoading}
        </div>
      ) : null}
      <div className="chat-first-opener__options chat-first-opener__options--inline chat-reply-styles" role="list">
        {(isFreeTier ? options.slice(0, 1) : options.slice(0, suggestCap)).map((o, idx) => {
          const meta = styleMetaFromPack(pack, o.style);
          return (
            <button
              key={`${o.style}-${idx}`}
              type="button"
              className={[
                "chat-reply-style",
                selectedIndex === idx ? "chat-reply-style--selected" : "",
                isPlusTier && idx === 0 ? "chat-reply-style--best" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              onClick={() => {
                if (disabled) return;
                void trackAnalyticsEvent("ai_used", {
                  surface: "timed_reply_suggestion",
                  tier: aiTier,
                  index: idx,
                  partner_user_id: partnerUserId,
                });
                void trackAnalyticsEvent(aiTier === "free" ? "ai_used_before_pay" : "ai_used_after_pay", {
                  surface: "timed_reply_suggestion",
                  index: idx,
                  partner_user_id: partnerUserId,
                });
                setSelectedIndex(idx);
                setChoiceFeedback(true);
                window.setTimeout(() => setChoiceFeedback(false), 1400);
                if (selectAnimTimerRef.current != null) window.clearTimeout(selectAnimTimerRef.current);
                selectAnimTimerRef.current = window.setTimeout(() => {
                  selectAnimTimerRef.current = null;
                  setSelectedIndex(null);
                }, 420);
                onInsert(o.text, { style: o.style, index: idx });
              }}
              disabled={disabled}
            >
              <span className="chat-reply-style__label">{meta.label}</span>
              {isPlusTier && idx === 0 ? (
                <span className="chat-reply-style__ribbon" aria-label={t("chat.reply.bestOptionAria")}>
                  {t("chat.reply.bestOption")}
                </span>
              ) : null}
              <span className="chat-reply-style__text">{o.text}</span>
              <span className="chat-reply-style__hint">{meta.hint}</span>
            </button>
          );
        })}
      </div>
      {isFreeTier ? (
        <div className="caption" style={{ marginTop: 10, opacity: 0.82, lineHeight: 1.35 }}>
          <Link
            className="chat-ai-inline__upgrade"
            href="/premium?source=ai_inline_reply"
            onClick={() => void trackAnalyticsEvent("paywall_clicked", { source: "ai_limit", surface: "timed_reply_freemium_hint" })}
          >
            {pack.premiumCta}
          </Link>
          <span style={{ opacity: 0.85 }}>
            {" "}
            {t("common.emDash")} {pack.premiumHint}
          </span>
        </div>
      ) : null}
      {choiceFeedback ? (
        <div className="caption text-white/70" style={{ marginTop: 8 }}>
          {"Nice choice 😉"}
        </div>
      ) : null}
    </div>
  );
}
