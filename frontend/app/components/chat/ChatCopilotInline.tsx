"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage } from "../../../lib/chat/types";
import { conversationContext } from "../../../lib/chat/normalize";
import {
  activatePremiumTrial,
  emitViewerRefresh,
  fetchChatCopilot,
  fetchTimedReplies,
  postAiLearningEvent,
  postAiMemoryEvent,
  type ChatCopilotResponse,
} from "../../../lib/chat/api";
import { fetchAbCopy, type AbCopyMap } from "../../../lib/abCopy";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { useT } from "../../components/i18n/I18nProvider";
import { neyraAiLocaleDevLog, neyraChatSuggestionDevLog } from "../../../lib/chat/neyraAiLocaleLog";
import { detectMixedScripts, isTextLikelyInExpectedLanguage } from "../../../lib/chat/aiLanguageTone";
import type { AiLanguageToneContext } from "../../../lib/chat/api";
import { copilotFallbackFromPack } from "../../../lib/ai/chatFallbackReplies";
import { getChatFallbackPackForChatSuggestions } from "../../../lib/ai/contextualChatFallback";
import type { AiTier } from "../../../lib/chat/aiTier";
import { aiChatContextMessageLimit } from "../../../lib/chat/aiTier";
import { bumpAiUsageMoment } from "../../../lib/monetization/valueMoments";

type Props = {
  viewerUserId: number | null;
  partnerUserId: number | null;
  messages: ChatMessage[];
  draft: string;
  disabled?: boolean;
  timingNudgeType?: "now" | "wait" | "reengage" | "revive" | null;
  aiCtx?: AiLanguageToneContext;
  aiTier?: AiTier;
  onInsertDraft: (text: string, meta: { label: string; optionIndex: number }) => void;
  onMeta?: (meta: { lastInsertedText?: string; lastInsertedLabel?: string; optionIndex?: number } | null) => void;
};

function prefKey(viewerUserId: number) {
  return `ai:copilot_pref_tone:${viewerUserId}`;
}

function normalizeAiLocale(raw: string | null | undefined): string {
  const s = String(raw || "").trim().toLowerCase();
  if (!s) return "en";
  if (s.startsWith("zh")) return "zh";
  return s.slice(0, 2) || "en";
}

export function ChatCopilotInline({ viewerUserId, partnerUserId, messages, draft, disabled = false, timingNudgeType = null, aiCtx, aiTier = "premium", onInsertDraft, onMeta }: Props) {
  const { t, locale: uiLocaleTag } = useT("ChatCopilotInline");
  const lastPartnerPlainEarly = useMemo(() => {
    if (!partnerUserId) return "";
    const last = (messages || []).slice(-1)[0] ?? null;
    if (!last || Number(last.senderId) !== Number(partnerUserId)) return "";
    return String((last as any).content || "").trim();
  }, [messages, partnerUserId]);
  const replyPack = useMemo(
    () => getChatFallbackPackForChatSuggestions(uiLocaleTag, lastPartnerPlainEarly || null),
    [uiLocaleTag, lastPartnerPlainEarly],
  );
  const fallbackCopilot = useMemo((): ChatCopilotResponse => {
    const opts = copilotFallbackFromPack(replyPack);
    return {
      strategy: null,
      meeting_readiness: null,
      meeting_suggestion: null,
      best_option_index: 0,
      options: opts.map((o) => ({ label: o.label, text: o.text })),
      safety_notes: [],
    };
  }, [replyPack]);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<ChatCopilotResponse | null>(null);
  const [quotaMessage, setQuotaMessage] = useState<string>("");
  const [fallbackActive, setFallbackActive] = useState(false);
  const lastIncomingIdRef = useRef<string>("");
  const genRef = useRef(0);
  const insertedRef = useRef<{ text: string; label: string; idx: number } | null>(null);
  const sourceRef = useRef<"chat_copilot" | "timed_replies">("chat_copilot");
  const [autoEnabled, setAutoEnabled] = useState(true);
  const pausedTypingRef = useRef(false);
  const pauseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cacheRef = useRef(new Map<string, ChatCopilotResponse>());
  const copilotLimitHitRef = useRef(false);
  const [abAiLimit, setAbAiLimit] = useState<AbCopyMap>({});
  const suppressAutoUntilManualRef = useRef(false);
  const activeAiLocale = useMemo(
    () => normalizeAiLocale((aiCtx as any)?.overrideLanguage || (aiCtx as any)?.uiLocale || uiLocaleTag),
    [aiCtx, uiLocaleTag],
  );

  useEffect(() => {
    suppressAutoUntilManualRef.current = true;
    cacheRef.current.clear();
    setData(null);
    setLoading(false);
    setFallbackActive(false);
    setQuotaMessage("");
  }, [activeAiLocale]);

  const ctx = useMemo(() => conversationContext(messages, aiChatContextMessageLimit(aiTier)), [messages, aiTier]);

  const fetchAiLimitAb = Boolean(data && (data as any).limited);
  useEffect(() => {
    if (!fetchAiLimitAb || viewerUserId == null) return;
    void fetchAbCopy(["ai.limit.copy"]).then(setAbAiLimit);
  }, [fetchAiLimitAb, viewerUserId]);

  const lastIncoming = useMemo(() => {
    if (!partnerUserId) return null;
    const last = (messages || []).slice(-1)[0] ?? null;
    if (!last) return null;
    if (last.senderId !== partnerUserId) return null;
    return last;
  }, [messages, partnerUserId]);

  useEffect(() => {
    // Pause-typing detector (debounced). We only auto-generate when the user stops typing.
    if (pauseTimerRef.current) clearTimeout(pauseTimerRef.current);
    // Default to "paused" when draft is empty so suggestions can appear immediately on thread open.
    pausedTypingRef.current = !draft.trim();
    pauseTimerRef.current = setTimeout(() => {
      pausedTypingRef.current = true;
    }, 900);
    return () => {
      if (pauseTimerRef.current) {
        clearTimeout(pauseTimerRef.current);
        pauseTimerRef.current = null;
      }
    };
  }, [draft]);

  useEffect(() => {
    // Simple "edited after insert" signal.
    const ins = insertedRef.current;
    if (!ins) return;
    if (!draft.trim()) return;
    if (draft.trim() === ins.text.trim()) return;
    const original = ins.text.trim();
    const editedText = draft.trim();
    const diffRatio = Math.min(1, Math.abs(editedText.length - original.length) / Math.max(1, original.length));
    const edit_distance_level = diffRatio < 0.18 ? "low" : diffRatio < 0.45 ? "medium" : "high";
    insertedRef.current = null;
    void trackAnalyticsEvent("ai_copilot_option_edited", { label: ins.label, option_index: ins.idx });
    if (partnerUserId)
      void postAiMemoryEvent({
        event_type: "option_edited",
        partner_user_id: partnerUserId,
        metadata_json: { edit_distance_level },
      }).catch(() => {});
  }, [draft]);

  function expectedLanguage(): string {
    const lang = String((aiCtx as any)?.overrideLanguage || (aiCtx as any)?.language || (aiCtx as any)?.uiLocale || "").trim();
    return normalizeAiLocale(lang || "en");
  }

  function validatePack(pack: ChatCopilotResponse | null): boolean {
    if (!pack?.options?.length) return false;
    const lang = expectedLanguage();
    const joined = pack.options.map((o) => String(o.text || "")).join(" ");
    if (detectMixedScripts(joined)) return false;
    return pack.options.every((o) => isTextLikelyInExpectedLanguage(lang, String(o.text || "")));
  }

  const onGenerate = async () => {
    if (disabled) return;
    if (!viewerUserId || !partnerUserId) return;
    if (!lastIncoming) return;
    if (timingNudgeType === "wait") return;
    const incomingId = String(lastIncoming.rawId ?? lastIncoming.id ?? lastIncoming.createdAt ?? "");
    if (incomingId) lastIncomingIdRef.current = incomingId;

    const gen = (genRef.current += 1);
    setQuotaMessage("");
    setFallbackActive(false);
    setLoading(true);
    setData(null);
    suppressAutoUntilManualRef.current = false;

    const preferredTone = typeof window !== "undefined" ? (localStorage.getItem(prefKey(viewerUserId)) || "").trim() : "";
    void trackAnalyticsEvent("ai_copilot_requested", { tier: "unknown", context_messages_count: ctx.length });
    neyraAiLocaleDevLog("requesting suggestions", {
      endpoint: timingNudgeType ? "timed-replies" : "chat-copilot",
      locale: uiLocaleTag,
      partnerUserId,
      nudgeType: timingNudgeType || "now",
    });

    try {
      if (timingNudgeType) {
        const timedResult = await fetchTimedReplies({
          messages: (messages || [])
            .slice(-30)
            .map((m) => ({
              role: viewerUserId != null && Number(m.senderId) === Number(viewerUserId) ? ("me" as const) : ("them" as const),
              text: String(m.content || "").trim(),
            }))
            .filter((m) => m.text),
          nudgeType: timingNudgeType,
          interestStage: null,
          mutualityScore: null,
          aiCtx,
          partnerUserId,
        });
        const timed = timedResult.options;
        if (genRef.current !== gen) return;
        const labels = [replyPack.easyLabel, replyPack.flirtyLabel, replyPack.deepLabel];
        const options = timed.map((o, idx) => ({
          label: labels[idx] ?? replyPack.easyLabel,
          text: o.text,
        }));
        const next = options.length
          ? ({ strategy: null, meeting_readiness: null, meeting_suggestion: null, options, safety_notes: [] } as any)
          : fallbackCopilot;
        const timedLocale = normalizeAiLocale(timedResult.locale || "");
        if (timedLocale && timedLocale !== expectedLanguage()) {
          setQuotaMessage(t("chat.suggestions.languageMismatchRetry"));
          setData(null);
          return;
        }
        sourceRef.current = "timed_replies";
        if (validatePack(next)) {
          neyraAiLocaleDevLog("received suggestions", { endpoint: "timed-replies", locale: uiLocaleTag, partnerUserId });
          neyraChatSuggestionDevLog({
            component: "ChatCopilotInline",
            endpoint: "/api/v1/ai/timed-replies",
            locale: uiLocaleTag,
            source: timingNudgeType || "now_emergency",
            fallback: next === fallbackCopilot,
            last_message_preview: lastPartnerPlainEarly.slice(0, 220),
          });
          setData(next);
        } else setData(null);
      } else {
        const res = await fetchChatCopilot({
          partnerUserId,
          userSelectedStyle: preferredTone || null,
          aiCtx,
        });
        if (genRef.current !== gen) return;
        if (normalizeAiLocale(res?.locale || "") !== expectedLanguage()) {
          setQuotaMessage(t("chat.suggestions.languageMismatchRetry"));
          setData(null);
          return;
        }
        const next = res && res.options.length ? res : fallbackCopilot;
        sourceRef.current = "chat_copilot";
        if (aiTier === "free" && res && res.options.length && !(res as any)?.limited) {
          bumpAiUsageMoment(1);
        }
        if (validatePack(next)) {
          neyraAiLocaleDevLog("received suggestions", { endpoint: "chat-copilot", locale: uiLocaleTag, partnerUserId });
          neyraChatSuggestionDevLog({
            component: "ChatCopilotInline",
            endpoint: "/api/v1/ai/chat-copilot",
            locale: uiLocaleTag,
            source: sourceRef.current,
            fallback: next === fallbackCopilot,
            last_message_preview: lastPartnerPlainEarly.slice(0, 220),
          });
          setData(next);
        } else setData(null);
      }
      void postAiLearningEvent({ name: "ai_options_shown" }).catch(() => {});
      if (partnerUserId)
        void postAiMemoryEvent({
          event_type: "option_shown",
          partner_user_id: partnerUserId,
          metadata_json: { source: sourceRef.current, nudge_type: timingNudgeType || "now" },
        }).catch(() => {});
    } catch (error) {
      if (genRef.current !== gen) return;
      const msg = error instanceof Error ? error.message : String(error);
      // Calm UX: if quota/rate limited, show safe fallback pack and a non-scary banner.
      if (msg.toLowerCase().includes("quota") || msg.toLowerCase().includes("429") || msg.toLowerCase().includes("rate limit")) {
        setFallbackActive(true);
        neyraChatSuggestionDevLog({
          component: "ChatCopilotInline",
          endpoint: timingNudgeType ? "/api/v1/ai/timed-replies" : "/api/v1/ai/chat-copilot",
          locale: uiLocaleTag,
          source: "quota_fallback",
          fallback: true,
          last_message_preview: lastPartnerPlainEarly.slice(0, 220),
        });
        setData(fallbackCopilot);
        return;
      }
      setData(null);
    } finally {
      if (genRef.current === gen) setLoading(false);
    }
  };

  // Auto-run: new incoming message + user paused typing + no draft.
  useEffect(() => {
    if (!autoEnabled) return;
    if (disabled) return;
    if (!viewerUserId || !partnerUserId) return;
    if (!lastIncoming) return;
    if (timingNudgeType === "wait") return;
    if (draft.trim()) return;
    const incomingId = String(lastIncoming.rawId ?? lastIncoming.id ?? lastIncoming.createdAt ?? "");
    if (!incomingId) return;
    const toneKey = String((aiCtx as any)?.overrideTone || (aiCtx as any)?.tone || "").trim() || "auto";
    const key = `${partnerUserId}:${incomingId}:${timingNudgeType || "now"}:${uiLocaleTag}:${expectedLanguage()}:${toneKey}`;
    if (suppressAutoUntilManualRef.current) return;
    if (cacheRef.current.has(key)) {
      const cached = cacheRef.current.get(key)!;
      setData(cached);
      lastIncomingIdRef.current = incomingId;
      return;
    }
    // Only when the user is not actively typing.
    if (!pausedTypingRef.current) return;
    void (async () => {
      const before = genRef.current;
      await onGenerate();
      if (genRef.current !== before) {
        const next = (data as any) as ChatCopilotResponse | null;
        if (next && validatePack(next)) cacheRef.current.set(key, next);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoEnabled, disabled, viewerUserId, partnerUserId, lastIncoming?.id, lastIncoming?.rawId, lastIncoming?.createdAt, timingNudgeType, draft, uiLocaleTag, aiCtx]);

  useEffect(() => {
    copilotLimitHitRef.current = false;
  }, [partnerUserId]);

  useEffect(() => {
    const limited = Boolean((data as any)?.limited);
    if (!limited) return;
    if (copilotLimitHitRef.current) return;
    copilotLimitHitRef.current = true;
    void trackAnalyticsEvent("ai_limit_hit", { surface: "chat_copilot_limited", partner_user_id: partnerUserId });
  }, [data, partnerUserId]);

  if (!partnerUserId) return null;
  if (!lastIncoming) return null;
  if (timingNudgeType === "wait") return null;

  if (quotaMessage) {
    return (
      <div className="chat-ai-replies">
        <div className="chat-ai-replies__label">{t("chat.ai.copilot.title")}</div>
        <div style={{ padding: "10px 12px", borderRadius: 14, border: "1px solid rgba(255, 138, 91, 0.25)", background: "rgba(255, 138, 91, 0.08)" }}>
          {quotaMessage}
        </div>
        <button type="button" className="btn btn-ghost" onClick={() => void onGenerate()} disabled={disabled || loading} style={{ marginTop: 10, justifySelf: "start" }}>
          {t("common.tryAgain")}
        </button>
      </div>
    );
  }

  if (fallbackActive && data) {
    // Show a soft banner: suggestions still work; AI provider is temporarily in fallback/cooldown.
    // Kept local to avoid any noisy global alerts.
  }

  if (!data) {
    return (
      <div className="chat-ai-replies">
        <div className="chat-ai-replies__label">{t("chat.ai.copilot.title")}</div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <button type="button" className="btn btn-primary" onClick={() => void onGenerate()} disabled={disabled || loading}>
            {t("chat.ai.multi.generate")}
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => setAutoEnabled((v) => !v)} disabled={disabled || loading}>
            {autoEnabled ? t("chat.ai.multi.autoOn") : t("chat.ai.multi.autoOff")}
          </button>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="chat-ai-replies">
        <div className="chat-ai-replies__label">{t("chat.ai.copilot.title")}</div>
        <div className="chat-ai-replies__row">
          <div className="chat-ai-replies__skeleton" />
          <div className="chat-ai-replies__skeleton" />
          <div className="chat-ai-replies__skeleton" />
        </div>
      </div>
    );
  }

  if (!data.options.length) return null;

  const premiumVisible = Boolean((data.strategy || "").trim() || data.meeting_readiness != null || (data.meeting_suggestion || "").trim());
  const devForcePremiumUi =
    typeof process !== "undefined" &&
    Boolean((process as any).env?.NEXT_PUBLIC_DEV_FORCE_PREMIUM) &&
    String((process as any).env?.NEXT_PUBLIC_DEV_FORCE_PREMIUM || "").trim() !== "0" &&
    String((process as any).env?.NEXT_PUBLIC_DEV_FORCE_PREMIUM || "").trim().toLowerCase() !== "false";
  const shouldUpsellTrial = devForcePremiumUi ? false : true; // In dev override mode, keep UI clean.
  const isLimited = Boolean((data as any).limited);
  const stall = (data as any).stall as { is_stalled?: boolean; stall_score?: number; reasons?: string[] } | null | undefined;
  const isStalled = Boolean(stall && stall.is_stalled);
  const stallReasons = Array.isArray(stall?.reasons) ? stall!.reasons!.map((x) => String(x || "").trim()).filter(Boolean).slice(0, 4) : [];
  const stallReasonLocalized = (r: string) => {
    const key = String(r || "").toLowerCase();
    if (key.includes("short")) return t("chat.ai.copilot.stall.short");
    if (key.includes("no question") || key.includes("no questions")) return t("chat.ai.copilot.stall.noQuestions");
    if (key.includes("pause")) return t("chat.ai.copilot.stall.pause");
    if (key.includes("cold") || key.includes("neutral")) return t("chat.ai.copilot.stall.lowEnergy");
    return t("chat.ai.copilot.stall.fallback", { raw: r });
  };
  const stallReasonText = stallReasons.length ? stallReasons.map(stallReasonLocalized).join(" + ") : "";
  const meetingSuggestionText = String((data as any).meeting_suggestion || "").trim();
  const meetingReadiness = data.meeting_readiness != null ? Number(data.meeting_readiness) : null;
  const isStageReady = Boolean(meetingSuggestionText);
  const bestIdxRaw = Number((data as any).best_option_index ?? 0);
  const bestIdx = Number.isFinite(bestIdxRaw) ? Math.max(0, Math.min(2, Math.trunc(bestIdxRaw))) : 0;

  return (
    <div className="chat-ai-replies">
      <div className="chat-ai-replies__label" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <span>{t("chat.ai.multi.title")}</span>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <button type="button" className="btn btn-ghost" onClick={() => void onGenerate()} disabled={disabled || loading}>
            {t("chat.ai.multi.regenerate")}
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => setAutoEnabled((v) => !v)} disabled={disabled || loading}>
            {autoEnabled ? t("chat.ai.multi.autoOn") : t("chat.ai.multi.autoOff")}
          </button>
        </div>
      </div>

      {fallbackActive ? (
        <div className="caption" style={{ opacity: 0.86, marginBottom: 10 }}>
          {t("chat.ai.fallbackActive")}
        </div>
      ) : null}

      {devForcePremiumUi ? (
        <div className="caption" style={{ opacity: 0.9, marginBottom: 10 }}>
          {t("chat.ai.copilot.devModePremium")}
        </div>
      ) : null}

      {isStalled ? (
        <div
          style={{
            marginBottom: 10,
            padding: "10px 12px",
            borderRadius: 14,
            border: "1px solid rgba(180, 120, 255, 0.22)",
            background: "rgba(180, 120, 255, 0.07)",
            display: "grid",
            gap: 6,
          }}
        >
          <div style={{ fontWeight: 900 }}>{t("chat.ai.copilot.stallTitle")}</div>
          {stallReasonText ? (
            <div className="caption" style={{ opacity: 0.9 }}>
              <strong>{t("chat.ai.copilot.stallReasonLabel")}</strong> {stallReasonText}
            </div>
          ) : null}
        </div>
      ) : null}

      {isLimited ? (
        <div
          style={{
            marginBottom: 10,
            padding: "12px 12px",
            borderRadius: 14,
            border: "1px solid rgba(180, 120, 255, 0.26)",
            background: "rgba(124, 92, 255, 0.10)",
            display: "grid",
            gap: 10,
          }}
        >
          <div style={{ fontWeight: 850, lineHeight: 1.35 }}>
            {(abAiLimit["ai.limit.copy"]?.text || "").trim() || t("chat.ai.limit.greatResponsesLine")}
          </div>
          <div className="caption" style={{ opacity: 0.85 }}>{t("chat.ai.copilot.premiumUpsellSubtitle")}</div>
          <Link
            className="btn btn-primary"
            href="/premium?source=chat_copilot_limit"
            style={{ justifySelf: "start", whiteSpace: "nowrap" }}
            onClick={() => void trackAnalyticsEvent("paywall_clicked", { source: "ai_limit", surface: "chat_copilot_limit_upsell" })}
          >
            {t("chat.ai.limit.ctaUpgrade")}
          </Link>
        </div>
      ) : null}

      {shouldUpsellTrial ? (
        <div
          style={{
            marginBottom: 10,
            padding: "10px 12px",
            borderRadius: 14,
            border: "1px solid rgba(255, 138, 91, 0.25)",
            background: "rgba(255, 138, 91, 0.08)",
            display: "grid",
            gap: 4,
          }}
        >
          <div style={{ fontWeight: 850 }}>{t("chat.ai.copilot.trialTitle")}</div>
          <div className="caption" style={{ opacity: 0.85 }}>
            {t("chat.ai.copilot.trialHint")}
          </div>
        </div>
      ) : null}

      {premiumVisible ? (
        <div style={{ display: "grid", gap: 8 }}>
          {data.strategy ? (
            <div className="caption" style={{ opacity: 0.9 }}>
              <strong>{t("chat.ai.copilot.strategyLabel")}</strong> {data.strategy}
            </div>
          ) : null}
          {data.meeting_readiness != null ? (
            <div className="caption" style={{ opacity: 0.9 }}>
              <strong>{t("chat.ai.copilot.meetingReadiness")}</strong> {Math.max(0, Math.min(100, Math.trunc(Number(data.meeting_readiness))))}%
            </div>
          ) : null}
          {isStageReady && meetingSuggestionText ? (
            <div
              style={{
                marginTop: 4,
                padding: "10px 12px",
                borderRadius: 14,
                border: "1px solid rgba(180, 120, 255, 0.25)",
                background: "rgba(180, 120, 255, 0.08)",
                display: "grid",
                gap: 8,
              }}
            >
              <div style={{ fontWeight: 900 }}>{t("chat.ai.copilot.meetingSuggestTitle")}</div>
              <div className="caption" style={{ opacity: 0.92 }}>
                {meetingSuggestionText}
              </div>
              <button
                type="button"
                className="btn btn-primary"
                disabled={disabled || isLimited}
                onClick={() => {
                  const cleaned = meetingSuggestionText.trim();
                  if (!cleaned) return;
                  if (partnerUserId)
                    void postAiMemoryEvent({
                      event_type: "meeting_suggested",
                      partner_user_id: partnerUserId,
                      metadata_json: { source: sourceRef.current, nudge_type: timingNudgeType || "now" },
                    }).catch(() => {});
                  onInsertDraft(cleaned, { label: t("chat.ai.copilot.optionMeeting"), optionIndex: -1 });
                }}
                style={{ justifySelf: "start", whiteSpace: "nowrap" }}
              >
                {t("chat.ai.copilot.insert")}
              </button>
            </div>
          ) : null}
          {data.meeting_suggestion ? (
            <div className="caption" style={{ opacity: 0.9 }}>
              <strong>{t("chat.ai.copilot.meetingSoftLabel")}</strong> {data.meeting_suggestion}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="chat-ai-replies__row">
        {data.options.slice(0, 3).map((o, idx) => (
          <div
            key={`${idx}:${o.label}:${o.text}`}
            className={`chat-ai-replies__option${isLimited ? " chat-ai-replies__option--locked" : ""}`.trim()}
            style={
              idx === bestIdx && !isLimited
                ? {
                    transform: "scale(1.02)",
                    border: "1px solid rgba(180, 120, 255, 0.40)",
                    boxShadow: "0 0 0 2px rgba(180, 120, 255, 0.14), 0 10px 28px rgba(180, 120, 255, 0.18)",
                  }
                : undefined
            }
          >
            <div className="chat-ai-replies__text">
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 6 }}>
                <div className="text-purple-300" style={{ fontWeight: 900 }}>
                  {idx === 0 ? t("chat.ai.multi.tone.playful") : idx === 1 ? t("chat.ai.multi.tone.flirty") : t("chat.ai.multi.tone.confident")}
                </div>
                {idx === bestIdx && !isLimited ? <div className="chat-ai-inline__best-pill">{t("chat.brain.best")}</div> : null}
              </div>
              <div
                style={
                  isLimited && idx === 0
                    ? {
                        maxHeight: 44,
                        overflow: "hidden",
                        WebkitMaskImage: "linear-gradient(to bottom, black 55%, transparent 100%)",
                        maskImage: "linear-gradient(to bottom, black 55%, transparent 100%)",
                      }
                    : isLimited
                      ? { filter: "blur(4px)" }
                      : undefined
                }
              >
                <span className="text-white/90">{o.text}</span>
              </div>
            </div>
            <div style={{ display: "flex", gap: 10, marginTop: 10, flexWrap: "wrap" }}>
              <button
                type="button"
                className="btn btn-primary"
                disabled={disabled || isLimited}
                onClick={() => {
                  const cleaned = String(o.text || "").trim();
                  if (!cleaned) return;
                  const label = idx === 0 ? "playful" : idx === 1 ? "flirty" : "confident";
                  insertedRef.current = { text: cleaned, label, idx };
                  onMeta?.({ lastInsertedText: cleaned, lastInsertedLabel: label, optionIndex: idx });
                  void trackAnalyticsEvent("ai_multi_suggestion_used", { tone: label, option_index: idx });
                  onInsertDraft(cleaned, { label, optionIndex: idx });
                  void (async () => {
                    try {
                      void trackAnalyticsEvent("paywall_cta_clicked", {
                        cta_label: "start_trial",
                        surface: "chat_copilot_suggestion_use",
                        tone: label,
                        option_index: idx,
                      });
                      const started = await activatePremiumTrial("ai_suggestion_clicked");
                      if (started) emitViewerRefresh("trial_started");
                    } catch {
                      // ignore
                    }
                  })();
                  const style: any = idx === 0 ? "light" : idx === 1 ? "flirty" : "deep";
                  void postAiLearningEvent({ name: "ai_option_selected", style, index: idx }).catch(() => {});
                  if (partnerUserId)
                    void postAiMemoryEvent({
                      event_type: "option_selected",
                      partner_user_id: partnerUserId,
                      metadata_json: { style, option_index: idx, nudge_type: timingNudgeType || "now", source: sourceRef.current },
                    }).catch(() => {});
                }}
              >
                {t("chat.ai.multi.use")}
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={disabled || isLimited}
                onClick={() => {
                  const cleaned = String(o.text || "").trim();
                  if (!cleaned) return;
                  const label = idx === 0 ? "playful" : idx === 1 ? "flirty" : "confident";
                  insertedRef.current = { text: cleaned, label, idx };
                  void trackAnalyticsEvent("ai_multi_suggestion_edit", { tone: label, option_index: idx });
                  onInsertDraft(cleaned, { label, optionIndex: idx });
                }}
              >
                {t("chat.ai.multi.edit")}
              </button>
              <button type="button" className="btn btn-ghost" disabled={disabled || loading} onClick={() => void onGenerate()}>
                {t("chat.ai.multi.regenerate")}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

