"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { getAiRewriteVariants, type AiRewriteMode } from "../../../lib/chat/api";
import { AI_DEBUG_ENABLED, FORCE_AI_VISIBLE, logAiGate } from "../../../lib/aiDebug";
import { useT } from "../i18n/I18nProvider";
import { Skeleton } from "../ui";
import { AiDebugPill } from "../AiDebugPill";
import type { AiLanguageToneContext } from "../../../lib/chat/api";
import {
  draftStateFromDraft,
  threadStateFromMessages,
  trackAiAssistDismissed,
  trackAiAssistLimitReached,
  trackAiAssistRequested,
  trackAiAssistSuggestionSelected,
  trackAiAssistUpgradeClicked,
  type AiAssistMode,
} from "../../../lib/chat/aiAssistAnalytics";
import { incrementFreeAiAssistUsedToday } from "../../../lib/chat/aiAssistUsage";
import type { AiTier } from "../../../lib/chat/aiTier";

type Props = {
  threadId: number | string;
  messagesLength: number;
  draft: string;
  conversationContext: string[];
  aiTier: AiTier;
  assistsLeftToday: number | null;
  onConsumedFreeAssist: () => void;
  disabled?: boolean;
  visible: boolean;
  autoRun?: { mode: AiRewriteMode; nonce: number } | null;
  aiCtx?: AiLanguageToneContext;
  onReplaceDraft: (text: string, meta: { mode: AiRewriteMode; suggestion: string }) => void;
  onClose: () => void;
};

function assistModeFromRewrite(mode: AiRewriteMode): AiAssistMode {
  if (mode === "natural") return "more_natural";
  if (mode === "shorter") return "shorter";
  return "polish";
}

export function ChatAiRewriteInline({
  threadId,
  messagesLength,
  draft,
  conversationContext,
  aiTier,
  assistsLeftToday,
  onConsumedFreeAssist,
  disabled = false,
  visible,
  autoRun,
  aiCtx,
  onReplaceDraft,
  onClose,
}: Props) {
  const { t } = useT("ChatAiRewriteInline");
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [bestSuggestionIndex, setBestSuggestionIndex] = useState<number>(-1);
  const [lastMode, setLastMode] = useState<AiRewriteMode>("polish");
  const [showMoreAlternatives, setShowMoreAlternatives] = useState(false);
  const lastRequestGenRef = useRef(0);
  const limitTrackedRef = useRef(false);
  const lastAutoRunNonceRef = useRef<number>(0);

  const trimmedDraft = useMemo(() => (draft ?? "").trim(), [draft]);
  const show = visible && Boolean(trimmedDraft);
  const freeLimitReached = aiTier === "free" && (assistsLeftToday ?? 0) <= 0;

  useEffect(() => {
    setSuggestions([]);
    setBestSuggestionIndex(-1);
    setShowMoreAlternatives(false);
  }, [threadId]);

  useEffect(() => {
    if (!show) {
      setSuggestions([]);
      setBestSuggestionIndex(-1);
      setShowMoreAlternatives(false);
    }
  }, [show]);

  async function run(mode: AiRewriteMode) {
    if (!show || disabled || loading) return;
    if (freeLimitReached) {
      if (!limitTrackedRef.current) {
        limitTrackedRef.current = true;
        void trackAiAssistLimitReached({
          assist_type: "rewrite",
          mode: assistModeFromRewrite(mode),
          thread_state: threadStateFromMessages(messagesLength),
          draft_state: draftStateFromDraft(draft),
          source: "inline_panel",
          plan_tier: aiTier,
          assists_left: assistsLeftToday ?? 0,
        });
      }
      return;
    }

    setLastMode(mode);
    setLoading(true);
    setSuggestions([]);
    setBestSuggestionIndex(-1);
    setShowMoreAlternatives(false);
    const gen = (lastRequestGenRef.current += 1);
    try {
      void trackAiAssistRequested({
        assist_type: "rewrite",
        mode: assistModeFromRewrite(mode),
        thread_state: threadStateFromMessages(messagesLength),
        draft_state: draftStateFromDraft(draft),
        source: "inline_panel",
        plan_tier: aiTier,
      });
      const rows = await getAiRewriteVariants(threadId, trimmedDraft, { conversationContext, mode, aiCtx });
      if (lastRequestGenRef.current !== gen) return;
      const next = rows.slice(0, 3);
      setSuggestions(next);
      if (next.length > 0) {
        let best = 0;
        let bestScore = Number.POSITIVE_INFINITY;
        for (let i = 0; i < next.length; i += 1) {
          const s = (next[i] ?? "").trim();
          const len = s.length;
          const q = s.includes("?") || s.includes("？");
          const score = Math.abs(len - 120) + (q ? 0 : 14) + (len < 25 ? 40 : 0);
          if (score < bestScore) {
            bestScore = score;
            best = i;
          }
        }
        setBestSuggestionIndex(best);
      }
      if (aiTier === "free" && next.length > 0 && lastRequestGenRef.current === gen) {
        incrementFreeAiAssistUsedToday();
        onConsumedFreeAssist();
      }
    } finally {
      if (lastRequestGenRef.current === gen) setLoading(false);
    }
  }

  useEffect(() => {
    if (!show || disabled || freeLimitReached || loading) return;
    if (suggestions.length > 0) return;
    void run("polish");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [show, trimmedDraft, threadId, disabled, freeLimitReached, loading, suggestions.length]);

  useEffect(() => {
    if (!autoRun) return;
    if (!autoRun.nonce) return;
    if (autoRun.nonce === lastAutoRunNonceRef.current) return;
    lastAutoRunNonceRef.current = autoRun.nonce;
    const m = autoRun.mode;
    const premiumOnlyMode =
      m === ("flirty" as AiRewriteMode) ||
      m === ("witty" as AiRewriteMode) ||
      m === ("charming" as AiRewriteMode) ||
      m === ("direct" as AiRewriteMode) ||
      m === ("thoughtful" as AiRewriteMode) ||
      m === ("tease_lightly" as AiRewriteMode) ||
      m === ("confident" as AiRewriteMode) ||
      m === ("softer" as AiRewriteMode) ||
      m === ("romantic" as AiRewriteMode) ||
      m === ("deep" as AiRewriteMode) ||
      m === ("playful" as AiRewriteMode);
    const isPaidTier = aiTier === "premium" || aiTier === "premium_plus";
    void run(premiumOnlyMode && !isPaidTier ? "polish" : m);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun?.nonce]);

  useEffect(() => {
    logAiGate("chat-rewrite-inline", {
      forceVisible: FORCE_AI_VISIBLE,
      visible,
      show,
      disabled,
      loading,
      freeLimitReached,
      aiTier,
      assistsLeftToday,
      hasDraft: Boolean(trimmedDraft),
      suggestionCount: suggestions.length,
      lastMode,
    });
  }, [aiTier, assistsLeftToday, disabled, freeLimitReached, lastMode, loading, show, suggestions.length, trimmedDraft, visible]);

  const primaryIndex = bestSuggestionIndex >= 0 ? bestSuggestionIndex : suggestions.length > 0 ? 0 : -1;
  const primaryText = primaryIndex >= 0 ? (suggestions[primaryIndex] ?? "").trim() : "";
  const alternativeLines = useMemo(() => {
    if (primaryIndex < 0 || !suggestions.length) return [];
    return suggestions
      .map((text, i) => ({ text: text.trim(), i }))
      .filter((x) => x.i !== primaryIndex && x.text)
      .slice(0, 3);
  }, [primaryIndex, suggestions]);

  useEffect(() => {
    setShowMoreAlternatives(false);
  }, [primaryIndex, trimmedDraft]);

  const pickSuggestion = (text: string, suggestion_index: 0 | 1 | 2) => {
    const mode = lastMode;
    void trackAiAssistSuggestionSelected({
      assist_type: "rewrite",
      mode: assistModeFromRewrite(mode),
      thread_state: threadStateFromMessages(messagesLength),
      draft_state: draftStateFromDraft(draft),
      source: "inline_panel",
      plan_tier: aiTier,
      suggestion_index,
    });
    onReplaceDraft(text, { mode, suggestion: text });
  };

  if (!show) return null;

  return (
    <div className="chat-ai-inline chat-ai-inline--simple" aria-label={t("chat.ai.rewrite.ariaPanel")}>
      <div className="chat-ai-inline__top chat-ai-inline__top--simple">
        <span className="chat-ai-inline__badge">{t("common.ai")}</span>
        <button
          type="button"
          className="chat-ai-inline__close"
          onClick={() => {
            void trackAiAssistDismissed({
              assist_type: "rewrite",
              mode: assistModeFromRewrite(lastMode),
              thread_state: threadStateFromMessages(messagesLength),
              draft_state: draftStateFromDraft(draft),
              source: "inline_panel",
              plan_tier: aiTier,
            });
            onClose();
          }}
          disabled={disabled}
          aria-label={t("chat.ai.rewrite.ariaClose")}
        >
          ×
        </button>
      </div>

      <details className="chat-brain-panel__advanced chat-ai-inline__usage">
        <summary className="chat-brain-panel__advanced-summary">{t("chat.brain.advancedSettings")}</summary>
        <div className="chat-brain-panel__advanced-body" style={{ flexDirection: "column", alignItems: "stretch" }}>
          {AI_DEBUG_ENABLED && FORCE_AI_VISIBLE ? (
            <span className="caption">{t("chat.ai.debug.forcedDev")}</span>
          ) : aiTier === "free" ? (
            <span className="caption">{t("chat.ai.status.freeRemaining", { count: Math.max(0, assistsLeftToday ?? 0) })}</span>
          ) : (
            <span className="caption">
              {aiTier === "premium_plus" ? t("chat.ai.status.unlimitedPlus") : t("chat.ai.status.unlimited")}
            </span>
          )}
        </div>
      </details>

      <div className="chat-ai-inline__results">
        {loading ? (
          <div className="chat-ai-inline__skeleton" aria-busy>
            <Skeleton className="chat-ai__skeleton-row chat-ai-inline__skeleton-row" />
          </div>
        ) : freeLimitReached ? (
          <div className="chat-ai-inline__upsell" aria-live="polite">
            <div className="chat-ai-inline__upsell-text">{t("chat.ai.rewrite.upsellFree")}</div>
            <Link
              href="/subscription"
              className="chat-ai-inline__upgrade"
              onClick={() => {
                void trackAiAssistUpgradeClicked({
                  assist_type: "rewrite",
                  mode: assistModeFromRewrite(lastMode),
                  thread_state: threadStateFromMessages(messagesLength),
                  draft_state: draftStateFromDraft(draft),
                  source: "inline_panel",
                  plan_tier: aiTier,
                  assists_left: assistsLeftToday ?? 0,
                });
              }}
            >
              {t("chat.ai.upgradeCta")}
            </Link>
          </div>
        ) : primaryText ? (
          <div className="chat-brain-panel__simple-card">
            <div className="chat-brain-panel__simple-label">{t("chat.brain.tryThis")}</div>
            <p className="chat-brain-panel__simple-text">{primaryText}</p>
            <div className="chat-brain-panel__simple-actions">
              <button
                type="button"
                className="chat-brain-panel__btn chat-brain-panel__btn--primary"
                disabled={disabled}
                onClick={() => pickSuggestion(primaryText, Math.min(2, Math.max(0, primaryIndex)) as 0 | 1 | 2)}
              >
                {t("chat.brain.send")}
              </button>
              <button
                type="button"
                className="chat-brain-panel__btn"
                disabled={disabled || alternativeLines.length === 0}
                aria-expanded={showMoreAlternatives}
                onClick={() => setShowMoreAlternatives((v) => !v)}
              >
                {showMoreAlternatives ? t("chat.brain.moreOptionsHide") : t("chat.brain.moreOptions")}
              </button>
            </div>

            {showMoreAlternatives && alternativeLines.length > 0 ? (
              <div className="chat-brain-panel__alts" role="list" aria-label={t("chat.brain.alternativesAria")}>
                {alternativeLines.map(({ text, i }) => (
                  <button
                    key={`${i}:${text}`}
                    type="button"
                    className="chat-brain-panel__alt-row"
                    role="listitem"
                    onClick={() => pickSuggestion(text, Math.min(2, Math.max(0, i)) as 0 | 1 | 2)}
                  >
                    <span className="chat-brain-panel__alt-text">{text}</span>
                    <span className="chat-brain-panel__alt-use">{t("chat.brain.send")}</span>
                  </button>
                ))}
                <button
                  type="button"
                  className="chat-brain-panel__refresh-link"
                  disabled={disabled || loading}
                  onClick={() => {
                    setShowMoreAlternatives(false);
                    void run("polish");
                  }}
                >
                  {t("chat.brain.differentIdea")}
                </button>
              </div>
            ) : null}
          </div>
        ) : (
          <div className="chat-ai-inline__empty" aria-live="polite">
            {lastMode ? t("chat.ai.rewrite.emptyAfterRun") : t("chat.ai.rewrite.emptyIdle")}
          </div>
        )}
        <AiDebugPill
          label={
            !loading && !freeLimitReached && suggestions.length === 0 && show ? "Rewrite suggestions hidden: no suggestions returned." : null
          }
          style={{ marginTop: 10 }}
        />
      </div>
    </div>
  );
}
