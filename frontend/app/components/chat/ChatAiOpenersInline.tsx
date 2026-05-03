"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { getAiOpeners, type AiOpenerMatchContext, type AiOpenerStyle } from "../../../lib/chat/api";
import { AI_DEBUG_ENABLED, FORCE_AI_VISIBLE, logAiGate } from "../../../lib/aiDebug";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { useT } from "../i18n/I18nProvider";
import { Button, Skeleton } from "../ui";
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
import { incrementFreeDailyUsed, getFreeDailyLeft } from "../../../lib/monetization/freeDaily";
import type { AiTier } from "../../../lib/chat/aiTier";
import { trackPremiumPlusHookClicked, trackPremiumPlusHookSeen } from "../../../lib/premiumPlusHooks";
import { buildSubscriptionHref, getPremiumPlusHookVariant, trackPremiumPlusHookVariant } from "../../../lib/premiumPlusHookOptimization";

type Props = {
  threadId: number | string;
  matchContext: AiOpenerMatchContext;
  conversationContext: string[];
  messagesLength: number;
  draft: string;
  aiTier: AiTier;
  assistsLeftToday: number | null;
  onConsumedFreeAssist: () => void;
  disabled?: boolean;
  /** Only render when the thread is empty + draft empty (parent controls). */
  visible: boolean;
  autoRun?: { style: AiOpenerStyle; nonce: number } | null;
  aiCtx?: AiLanguageToneContext;
  onInsert: (text: string, meta: { mode: AiAssistMode; suggestion_index: 0 | 1 | 2 }) => void;
  /** Send this suggestion as a message immediately (composer send path). */
  onSendNow: (text: string, meta: { mode: AiAssistMode; suggestion_index: 0 | 1 | 2 }) => void | Promise<void>;
  onClose: () => void;
};

type OpenerOptionKey = "easy" | "flirty" | "deep";
type OpenerOption = {
  key: OpenerOptionKey;
  label: string;
  text: string;
  why: string[];
  suggestion_index: 0 | 1 | 2;
};

const openerCache = new Map<string, { options: OpenerOption[]; bestIndex: number; at: number }>();

function stableSeed(): string {
  const n = Math.trunc(Math.random() * 1_000_000_000);
  return String(n);
}

function buildWhy(matchContext: AiOpenerMatchContext, t: (k: string, v?: any) => string, key: OpenerOptionKey): string[] {
  const bio = String(matchContext?.bio ?? "").trim();
  const interests = Array.isArray(matchContext?.interests) ? matchContext.interests.map((x) => String(x || "").trim()).filter(Boolean) : [];
  const city = String(matchContext?.city ?? "").trim();
  const hooks: string[] = [];
  if (bio) hooks.push(t("chat.ai.openers.why.bio"));
  if (interests.length) hooks.push(t("chat.ai.openers.why.interests", { value: interests.slice(0, 2).join(", ") }));
  if (city) hooks.push(t("chat.ai.openers.why.city", { value: city }));
  if (!hooks.length) hooks.push(t("chat.ai.openers.why.personal"));

  if (key === "easy") return [hooks[0] || t("chat.ai.openers.why.personal"), t("chat.ai.openers.why.easy")];
  if (key === "flirty") return [hooks[0] || t("chat.ai.openers.why.personal"), t("chat.ai.openers.why.flirty")];
  return [hooks[0] || t("chat.ai.openers.why.personal"), t("chat.ai.openers.why.deep")];
}

export function ChatAiOpenersInline({
  threadId,
  matchContext,
  conversationContext,
  messagesLength,
  draft,
  aiTier,
  assistsLeftToday,
  onConsumedFreeAssist,
  disabled = false,
  visible,
  autoRun,
  aiCtx,
  onInsert,
  onSendNow,
  onClose,
}: Props) {
  const { t, locale: i18nLocale } = useT("ChatAiOpenersInline");
  const [collapsed, setCollapsed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [options, setOptions] = useState<OpenerOption[]>([]);
  const [bestIndex, setBestIndex] = useState<number>(-1);
  const [lastStyle, setLastStyle] = useState<AiOpenerStyle>("default");
  const [emptyReason, setEmptyReason] = useState<string>("");
  const lastRequestGenRef = useRef(0);
  const [showPlusUpsell, setShowPlusUpsell] = useState(false);
  const plusHookSeenRef = useRef(false);
  const plusVariantRef = useRef(getPremiumPlusHookVariant("ai_styles"));

  const show = visible;
  const freeLimitReached = aiTier === "free" && (assistsLeftToday ?? 0) <= 0;
  const freeDailyOpenerLeft = aiTier === "free" ? getFreeDailyLeft("ai_opener", 1) : 1;
  const freeDailyOpenerExhausted = aiTier === "free" && freeDailyOpenerLeft <= 0;
  const canRun = show && !collapsed && !disabled && !loading && !freeLimitReached;
  const limitTrackedRef = useRef(false);
  const lastAutoRunNonceRef = useRef<number>(0);
  const lastSignatureRef = useRef<string>("");

  const matchName = useMemo(() => String(matchContext?.matchName ?? "").trim(), [matchContext]);
  const cacheKey = useMemo(
    () =>
      `${String(threadId)}:${String(matchName)}:${String(aiCtx?.uiLocale || i18nLocale || "")}`,
    [aiCtx?.uiLocale, i18nLocale, matchName, threadId],
  );

  async function run(style: AiOpenerStyle, _label?: string) {
    if (!show || collapsed || disabled || loading) return;
    setLastStyle(style);
    setShowPlusUpsell(false);
    setEmptyReason("");
    const mode: AiAssistMode =
      style === "playful"
        ? "playful"
        : style === "confident"
          ? "confident"
          : style === "warm"
            ? "warm"
            : style === "flirty"
              ? "flirty"
              : style === "witty"
                ? "witty"
                : style === "charming"
                  ? "charming"
                  : style === "direct"
                    ? "direct"
                    : style === "thoughtful"
                      ? "thoughtful"
                      : style === "tease_lightly"
                        ? "tease_lightly"
                        : "suggest_opener";

    const plusOnly = mode === "flirty" || mode === "witty" || mode === "charming" || mode === "direct" || mode === "thoughtful" || mode === "tease_lightly";
    if (plusOnly && aiTier !== "premium_plus") {
      setShowPlusUpsell(true);
      if (!plusHookSeenRef.current) {
        plusHookSeenRef.current = true;
        const v = plusVariantRef.current;
        void trackPremiumPlusHookVariant({ context: "ai_styles", plan_tier: aiTier, variant_id: v.variant_id, copy_id: v.copy_id, surface: "chat_openers_inline", thread_state: threadStateFromMessages(messagesLength) });
        void trackPremiumPlusHookSeen({
          context: "ai_styles",
          plan_tier: aiTier,
          thread_state: threadStateFromMessages(messagesLength),
          surface: "chat_openers_inline",
          variant_id: v.variant_id,
          copy_id: v.copy_id,
        });
      }
      void trackAiAssistUpgradeClicked({
        assist_type: "opener",
        mode,
        thread_state: threadStateFromMessages(messagesLength),
        draft_state: draftStateFromDraft(draft),
        source: "inline_panel",
        plan_tier: aiTier,
        assists_left: assistsLeftToday ?? undefined,
      });
      return;
    }

    if (freeLimitReached || freeDailyOpenerExhausted) {
      if (!limitTrackedRef.current) {
        limitTrackedRef.current = true;
        void trackAiAssistLimitReached({
          assist_type: "opener",
          mode,
          thread_state: threadStateFromMessages(messagesLength),
          draft_state: draftStateFromDraft(draft),
          source: "inline_panel",
        plan_tier: aiTier,
          assists_left: assistsLeftToday ?? 0,
        });
      }
      return;
    }

    setLoading(true);
    setOptions([]);
    setBestIndex(-1);
    const gen = (lastRequestGenRef.current += 1);
    try {
      void trackAiAssistRequested({
        assist_type: "opener",
        mode,
        thread_state: threadStateFromMessages(messagesLength),
        draft_state: draftStateFromDraft(draft),
        source: "inline_panel",
        plan_tier: aiTier,
      });
      const seed = stableSeed();
      const ctx = [...(conversationContext || []), `VARIATION_SEED:${seed}`].slice(-12);
      const res = await getAiOpeners(threadId, matchContext, { style, conversationContext: ctx, aiCtx });
      if (lastRequestGenRef.current !== gen) return;
      const items = Array.isArray(res.items) && res.items.length ? res.items : [];
      const suggestions = Array.isArray(res.suggestions) ? res.suggestions : [];
      if (suggestions.length === 0 && items.length === 0) {
        setEmptyReason(t("chat.ai.openers.errors.none"));
        // silent fail: hide panel if backend returns nothing
        void trackAiAssistDismissed({
          assist_type: "opener",
          mode,
          thread_state: threadStateFromMessages(messagesLength),
          draft_state: draftStateFromDraft(draft),
          source: "inline_panel",
          plan_tier: aiTier,
        });
        if (!AI_DEBUG_ENABLED) onClose();
        return;
      }
      const pickText = (typ: "safe" | "flirty" | "smart", fallbackIndex: 0 | 1 | 2) => {
        const fromItems = items.find((x: any) => String(x?.type || "").toLowerCase() === typ);
        return String(fromItems?.text || suggestions[fallbackIndex] || "").trim();
      };
      const nextOptions: OpenerOption[] = [
        { key: "easy" as const, label: t("chat.ai.openers.style.easy"), text: pickText("safe", 0), why: buildWhy(matchContext, t, "easy"), suggestion_index: 0 as const },
        { key: "flirty" as const, label: t("chat.ai.openers.style.flirty"), text: pickText("flirty", 1), why: buildWhy(matchContext, t, "flirty"), suggestion_index: 1 as const },
        { key: "deep" as const, label: t("chat.ai.openers.style.deep"), text: pickText("smart", 2), why: buildWhy(matchContext, t, "deep"), suggestion_index: 2 as const },
      ].filter((o) => Boolean(o.text));

      const signature = nextOptions.map((o) => o.text).join("|").slice(0, 900);
      if (signature && signature === lastSignatureRef.current) {
        // one retry for diversity
        lastSignatureRef.current = "";
        void run(style, _label);
        return;
      }
      lastSignatureRef.current = signature;

      setOptions(nextOptions);
      setBestIndex(Math.max(0, Math.min(nextOptions.length - 1, res.bestIndex ?? 1)));
      if (nextOptions.length) openerCache.set(cacheKey, { options: nextOptions, bestIndex: Math.max(0, Math.min(nextOptions.length - 1, res.bestIndex ?? 1)), at: Date.now() });
      if (aiTier === "free") {
        incrementFreeDailyUsed("ai_opener", 1);
        onConsumedFreeAssist();
      }
    } finally {
      if (lastRequestGenRef.current === gen) setLoading(false);
    }
  }

  useEffect(() => {
    if (!autoRun) return;
    if (!autoRun.nonce) return;
    if (autoRun.nonce === lastAutoRunNonceRef.current) return;
    lastAutoRunNonceRef.current = autoRun.nonce;
    void run(autoRun.style, t("chat.ai.openers.action.suggest"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun?.nonce]);

  useEffect(() => {
    if (!show || collapsed || disabled) return;
    if (!canRun) return;
    if (options.length) return;
    const cached = openerCache.get(cacheKey);
    if (cached && Date.now() - cached.at < 2 * 60_000) {
      setOptions(cached.options);
      setBestIndex(cached.bestIndex);
      return;
    }
    void run("default", t("chat.ai.openers.action.suggest"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [show, collapsed, disabled, canRun]);

  useEffect(() => {
    logAiGate("chat-openers-inline", {
      forceVisible: FORCE_AI_VISIBLE,
      visible,
      show,
      collapsed,
      disabled,
      loading,
      freeLimitReached,
      aiTier,
      assistsLeftToday,
      matchName,
      suggestionCount: options.length,
      emptyReason,
    });
  }, [aiTier, assistsLeftToday, collapsed, disabled, emptyReason, freeLimitReached, loading, matchName, show, options.length, visible]);

  if (!show) return null;

  return (
    <div className="chat-ai-inline" aria-label={t("chat.ai.openers.ariaPanel")}>
      <div className="chat-ai-inline__top">
        <button
          type="button"
          className="chat-ai-inline__toggle"
          onClick={() => setCollapsed((v) => !v)}
          disabled={disabled}
          aria-expanded={!collapsed}
        >
          <span className="chat-ai-inline__badge">{t("common.ai")}</span>
          <span className="chat-ai-inline__title">
            {matchName ? t("chat.ai.openers.titleWithName", { name: matchName }) : t("chat.ai.openers.title")}
          </span>
          <span className="chat-ai-inline__chev" aria-hidden>
            {collapsed ? "▾" : "▴"}
          </span>
        </button>
        <button
          type="button"
          className="chat-ai-inline__close"
          onClick={() => {
            const mode: AiAssistMode =
              lastStyle === "playful"
                ? "playful"
                : lastStyle === "confident"
                  ? "confident"
                  : lastStyle === "warm"
                    ? "warm"
                    : "suggest_opener";
            void trackAiAssistDismissed({
              assist_type: "opener",
              mode,
              thread_state: threadStateFromMessages(messagesLength),
              draft_state: draftStateFromDraft(draft),
              source: "inline_panel",
              plan_tier: aiTier,
            });
            onClose();
          }}
          disabled={disabled}
          aria-label={t("chat.ai.openers.ariaClose")}
        >
          ×
        </button>
      </div>

      <div className="chat-ai-inline__status" aria-label={t("chat.ai.status.aria")}>
        {AI_DEBUG_ENABLED && FORCE_AI_VISIBLE ? (
          <span className="chat-ai-inline__status-text">{t("chat.ai.debug.forcedDev")}</span>
        ) : aiTier === "free" ? (
          <span className="chat-ai-inline__status-text">{t("chat.ai.status.freeRemaining", { count: Math.max(0, assistsLeftToday ?? 0) })}</span>
        ) : (
          <span className="chat-ai-inline__status-text">
            {aiTier === "premium_plus" ? t("chat.ai.status.unlimitedPlus") : t("chat.ai.status.unlimited")}
          </span>
        )}
      </div>

      {collapsed ? null : (
        <>
          <div className="caption chat-ai-inline__tone-hint" style={{ marginTop: 6, opacity: 0.88, lineHeight: 1.35 }}>
            <div>{t("chat.ai.tone.adaptedToLanguage")}</div>
            {aiTier === "free" ? (
              <div style={{ marginTop: 4, opacity: 0.92 }}>{t("chat.ai.tone.premiumHint")}</div>
            ) : null}
          </div>
          <div className="chat-ai-inline__actions" role="group" aria-label={t("chat.ai.openers.ariaTones")}>
            <Button
              type="button"
              variant="ghost"
              disabled={disabled || loading || freeLimitReached}
              onClick={() => void run(lastStyle || "default", t("chat.ai.openers.action.suggest"))}
            >
              {t("chat.ai.openers.moreIdeas")}
            </Button>
          </div>

          <div className="chat-ai-inline__results">
            {loading ? (
              <div className="chat-ai-inline__skeleton" aria-busy>
                <Skeleton className="chat-ai__skeleton-row chat-ai-inline__skeleton-row" />
                <Skeleton className="chat-ai__skeleton-row chat-ai-inline__skeleton-row" />
                <Skeleton className="chat-ai__skeleton-row chat-ai-inline__skeleton-row" />
              </div>
            ) : freeLimitReached || freeDailyOpenerExhausted ? (
              <div className="chat-ai-inline__upsell" aria-live="polite">
                <div className="chat-ai-inline__upsell-text">{t("premium.freeUsedToday.ai")}</div>
                <Link
                  href="/subscription"
                  className="chat-ai-inline__upgrade"
                  onClick={() => {
                    void trackAiAssistUpgradeClicked({
                      assist_type: "opener",
                      mode:
                        lastStyle === "playful"
                          ? "playful"
                          : lastStyle === "confident"
                            ? "confident"
                            : lastStyle === "warm"
                              ? "warm"
                              : "suggest_opener",
                      thread_state: threadStateFromMessages(messagesLength),
                      draft_state: draftStateFromDraft(draft),
                      source: "inline_panel",
                      plan_tier: aiTier,
                      assists_left: assistsLeftToday ?? 0,
                    });
                  }}
                >
                  {t("premium.unlockUnlimited")}
                </Link>
              </div>
            ) : showPlusUpsell ? (
              <div className="chat-ai-inline__upsell" aria-live="polite">
                <div className="chat-ai-inline__upsell-text">{plusVariantRef.current.text}</div>
                <Link
                  href={buildSubscriptionHref("ai_styles", plusVariantRef.current.variant_id)}
                  className="chat-ai-inline__upgrade"
                  onClick={() => {
                    const v = plusVariantRef.current;
                    void trackPremiumPlusHookClicked({
                      context: "ai_styles",
                      plan_tier: aiTier,
                      thread_state: threadStateFromMessages(messagesLength),
                      surface: "chat_openers_inline",
                      variant_id: v.variant_id,
                      copy_id: v.copy_id,
                    });
                  }}
                >
                  {t("chat.ai.upgradeCta")}
                </Link>
              </div>
            ) : options.length > 0 ? (
              <div className="chat-ai-inline__suggestions">
                {options.map((opt, idx) => {
                  const isBest = bestIndex === idx;
                  const mode: AiAssistMode = opt.key === "easy" ? "suggest_opener" : opt.key === "flirty" ? "flirty" : "thoughtful";
                  return (
                    <div
                      key={`${opt.key}:${opt.text}`}
                      className={[
                        "chat-ai__suggestion",
                        "chat-ai-inline__suggestion",
                        isBest ? "chat-ai-inline__suggestion--best" : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                    >
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                        <div className="text-purple-300" style={{ fontWeight: 900 }}>{opt.label}</div>
                        {isBest ? <div className="chat-ai-inline__best-pill">🔥 {t("chat.ai.openers.bestChoice")}</div> : null}
                      </div>
                      <div className="chat-ai__suggestion-text text-white/90" style={{ marginTop: 8 }}>
                        {opt.text}
                      </div>
                      <div style={{ marginTop: 10, display: "flex", gap: 10, flexWrap: "wrap" }}>
                        <Button
                          type="button"
                          onClick={() => {
                            const cleaned = String(opt.text || "").trim();
                            if (!cleaned) return;
                            void trackAiAssistSuggestionSelected({
                              assist_type: "opener",
                              mode,
                              thread_state: threadStateFromMessages(messagesLength),
                              draft_state: draftStateFromDraft(draft),
                              source: "inline_panel",
                              plan_tier: aiTier,
                              suggestion_index: opt.suggestion_index,
                            });
                            void trackAnalyticsEvent("ai_assist_opener_sent_now", {
                              mode,
                              suggestion_index: opt.suggestion_index,
                              source: "inline_panel",
                            });
                            void Promise.resolve(onSendNow(cleaned, { mode, suggestion_index: opt.suggestion_index }));
                          }}
                          disabled={disabled}
                        >
                          {t("chat.ai.suggestion.send")}
                        </Button>
                        <Button
                          type="button"
                          variant="secondary"
                          onClick={() => {
                            void trackAiAssistSuggestionSelected({
                              assist_type: "opener",
                              mode,
                              thread_state: threadStateFromMessages(messagesLength),
                              draft_state: draftStateFromDraft(draft),
                              source: "inline_panel",
                              plan_tier: aiTier,
                              suggestion_index: opt.suggestion_index,
                            });
                            onInsert(opt.text, { mode, suggestion_index: opt.suggestion_index });
                          }}
                          disabled={disabled}
                        >
                          {t("chat.ai.suggestion.edit")}
                        </Button>
                      </div>
                      <div style={{ marginTop: 10 }}>
                        <div className="caption text-white/70" style={{ opacity: 0.9, fontWeight: 850 }}>
                          {t("chat.ai.openers.whyTitle")}
                        </div>
                        <ul className="caption text-white/70" style={{ margin: "8px 0 0", paddingLeft: "1.25rem", opacity: 0.92 }}>
                          {opt.why.slice(0, 2).map((line) => (
                            <li key={line} style={{ marginBottom: 4 }}>
                              {line}
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="chat-ai-inline__empty" aria-live="polite">
                {t("chat.ai.openers.emptyIdle")}
              </div>
            )}
            <AiDebugPill
              label={!loading && !showPlusUpsell && !freeLimitReached && options.length === 0 ? emptyReason : null}
              style={{ marginTop: 10 }}
            />
          </div>
        </>
      )}
    </div>
  );
}
