"use client";

import Link from "next/link";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { RateLimitError } from "../../../lib/api";
import {
  type ChatBrainRequestMode,
  type ChatBrainVariantKey,
  type ChatBrainSuggestionsResponse,
  type DatingConversationMode,
  postChatBrainSuggestions,
} from "../../../lib/chat/api";
import type { AiLanguageToneContext } from "../../../lib/chat/api";
import type { AiTier } from "../../../lib/chat/aiTier";
import { incrementFreeAiChatSuggestionsUsed } from "../../../lib/chat/aiChatUsage";
import type { ChatMessage } from "../../../lib/chat/types";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { useT } from "../i18n/I18nProvider";
import { translateApiUserMessage } from "../../../lib/i18n/translateApiUserMessage";
import { SUPPORTED_LOCALES, formatLocaleOptionLabel, type Locale } from "../../../lib/i18n";
import { getCurrentUiLocale } from "../../../lib/i18n";
import { normalizeLocaleInput } from "../../../lib/i18n/locales";
import { getChatFallbackPack } from "../../../lib/ai/chatFallbackReplies";
import {
  CHAT_BRAIN_LAST_GOOD_BY_PARTNER,
  CHAT_BRAIN_SUGGESTIONS_CACHE,
} from "../../../lib/chat/chatBrainSuggestionsCache";
import { mapApiConversationModeToDatingMode } from "../../../lib/chat/conversationStageStrategy";
import { neyraAiLocaleDevLog, neyraAiLocaleRenderedSuggestions, neyraAiLocaleRequestingSuggestions } from "../../../lib/chat/neyraAiLocaleLog";
import { bumpAiUsageMoment } from "../../../lib/monetization/valueMoments";
import { softMonClaimOnce } from "../../../lib/monetization/softMonSession";

const VARIANT_ORDER: ChatBrainVariantKey[] = ["light", "flirty", "deep"];

/** Single UX surface: always use smart / auto mode internally (no mode tabs). */
const BRAIN_TAB = "smart" as const;

export type BrainTab = "smart" | "opener" | "reply" | "revive" | "flirty" | "deep";

function tabToRequestMode(tab: BrainTab): ChatBrainRequestMode {
  if (tab === "smart") return "auto";
  if (tab === "deep") return "deepen";
  return tab;
}

export type ChatAiBrainPanelHandle = {
  /** Refresh suggestions (same as “Different idea”). */
  regenerateAll: () => void;
};

type Props = {
  partnerUserId: number | null;
  disabled?: boolean;
  viewerUserId?: number | null;
  messages?: ChatMessage[];
  /** When the composer "AI assist" drawer opens, load suggestions (cache-first) if none shown yet. */
  composerAiOpen?: boolean;
  /** Empty thread: tighter panel chrome (no large subtitle block). */
  threadIsEmpty?: boolean;
  /** Do not show suggestions identical to recent (including hidden AI/demo) texts. */
  blockedTexts?: string[];
  aiCtx?: AiLanguageToneContext;
  aiTier?: AiTier;
  /** Free tier: suggestions remaining today (enforces cap). Null = unlimited (premium). */
  freeAiChatSuggestionsLeft?: number | null;
  onFreeAiChatConsumed?: () => void;
  onInsertComposer: (
    text: string,
    meta: {
      brain_mode: string;
      variant: ChatBrainVariantKey;
      was_recommended: boolean;
      conversation_stage?: string | null;
      conversation_mode?: string | null;
    },
  ) => void;
};

type ToneOption = "auto" | "flirty" | "playful" | "confident" | "warm" | "direct" | "teasing" | "thoughtful";

function prefKey(partnerUserId: number) {
  return `ai:langtone:${partnerUserId}`;
}

function coachMoveLabel(move: string): string {
  return (
    {
      reply: "Reply",
      ask_question: "Ask a question",
      flirt: "Flirt",
      deepen: "Deepen",
      wait: "Wait",
      suggest_meet: "Suggest meet",
      revive: "Revive",
    } as Record<string, string>
  )[move] || "Reply";
}

function readinessLabel(value?: string | null): string {
  return (
    {
      not_ready: "Not ready",
      warming_up: "Warming up",
      ready_soft: "Ready softly",
      ready_direct: "Ready directly",
    } as Record<string, string>
  )[String(value || "")] || "Not ready";
}

function riskLabel(stallRisk?: number | null): string {
  const n = Number(stallRisk ?? 0);
  if (n >= 68) return "high";
  if (n >= 38) return "medium";
  return "low";
}

export const ChatAiBrainPanel = forwardRef<ChatAiBrainPanelHandle, Props>(function ChatAiBrainPanel(
  {
    partnerUserId,
    disabled = false,
    viewerUserId: _viewerUserId = null, // eslint-disable-line @typescript-eslint/no-unused-vars
    messages: _messages = [],
    composerAiOpen = false,
    threadIsEmpty = false,
    blockedTexts = [],
    aiCtx,
    aiTier = "premium",
    freeAiChatSuggestionsLeft = null,
    onFreeAiChatConsumed,
    onInsertComposer,
  },
  ref,
) {
  const { t, locale: i18nLocale } = useT("ChatAiBrainPanel");
  const uiLocale = getCurrentUiLocale();
  /** React i18n locale wins over getCurrentUiLocale() to avoid stale storage reads during switches. */
  const displayLocaleCode = useMemo(
    () => normalizeLocaleInput(String(i18nLocale || uiLocale || "en")) ?? "en",
    [i18nLocale, uiLocale],
  );
  const fb = useMemo(() => getChatFallbackPack(displayLocaleCode), [displayLocaleCode]);
  const [pack, setPack] = useState<ChatBrainSuggestionsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showMoreAlternatives, setShowMoreAlternatives] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const lastRequestAtRef = useRef(0);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inFlightKeyRef = useRef<string>("");
  const prevComposerAiOpenRef = useRef(false);
  const datingModeTouchedRef = useRef(false);
  const stageStrategyRef = useRef<{ suggested_tone: string; suggested_conversation_mode: string } | null>(null);
  const tRef = useRef(t);
  tRef.current = t;

  const [overrideLanguage, setOverrideLanguage] = useState<string>("");
  const [overrideTone, setOverrideTone] = useState<ToneOption>("auto");
  const [datingMode, setDatingMode] = useState<DatingConversationMode>("easy");

  const lastIncomingId = useMemo(() => {
    const pid = Number(partnerUserId || 0);
    if (!pid) return "";
    const msgs = Array.isArray(_messages) ? _messages : [];
    for (let i = msgs.length - 1; i >= 0; i -= 1) {
      const m: any = msgs[i] as any;
      if (Number(m?.senderId) !== pid) continue;
      const rid = m?.rawId ?? m?.id ?? m?.createdAt ?? "";
      const s = String(rid || "").trim();
      if (s) return s;
      break;
    }
    return "";
  }, [_messages, partnerUserId]);

  useEffect(() => {
    setDatingMode("easy");
    datingModeTouchedRef.current = false;
    stageStrategyRef.current = null;
  }, [partnerUserId]);

  useEffect(() => {
    if (!partnerUserId || typeof window === "undefined") return;
    try {
      const raw = localStorage.getItem(prefKey(partnerUserId));
      if (!raw) return;
      const parsed = JSON.parse(raw) as { tone?: unknown };
      const tone = typeof parsed.tone === "string" ? parsed.tone.trim() : "";
      if (tone) setOverrideTone((tone as ToneOption) || "auto");
    } catch {
      /* ignore */
    }
  }, [partnerUserId]);

  useEffect(() => {
    if (!partnerUserId || typeof window === "undefined") return;
    try {
      localStorage.setItem(prefKey(partnerUserId), JSON.stringify({ tone: overrideTone || "auto" }));
    } catch {
      /* ignore */
    }
  }, [overrideTone, partnerUserId]);

  const prevLocaleRef = useRef(i18nLocale);
  useEffect(() => {
    if (prevLocaleRef.current === i18nLocale) return;
    prevLocaleRef.current = i18nLocale;
    setOverrideLanguage("");
    // Locale switch must reset UI immediately and avoid reusing cached suggestions.
    abortRef.current?.abort();
    setPack(null);
    setError(null);
    setShowMoreAlternatives(false);
    CHAT_BRAIN_SUGGESTIONS_CACHE.clear();
    CHAT_BRAIN_LAST_GOOD_BY_PARTNER.clear();
  }, [i18nLocale]);

  const lang = useMemo(
    () => (overrideLanguage || String(i18nLocale || "").trim() || uiLocale || "en").trim() || "en",
    [overrideLanguage, i18nLocale, uiLocale],
  );
  const isPremiumTier = aiTier === "premium" || aiTier === "premium_plus";

  const requestKeyBase = useMemo(() => {
    const toneKey = (overrideTone || "auto").trim() || "auto";
    return `${String(partnerUserId || "")}:${lang}:${toneKey}:${String(lastIncomingId || "")}:${datingMode}`;
  }, [datingMode, lang, lastIncomingId, overrideTone, partnerUserId]);

  const freeLeftRef = useRef(freeAiChatSuggestionsLeft);
  freeLeftRef.current = freeAiChatSuggestionsLeft;
  const isFreeTier = aiTier === "free";
  const brainAiLimitHitRef = useRef(false);
  const aiLimitConversionShownRef = useRef(false);

  useEffect(() => {
    brainAiLimitHitRef.current = false;
    aiLimitConversionShownRef.current = false;
  }, [partnerUserId]);

  useEffect(() => {
    if (!isFreeTier) return;
    if (!composerAiOpen) return;
    if (freeAiChatSuggestionsLeft == null || freeAiChatSuggestionsLeft > 0) return;
    if (brainAiLimitHitRef.current) return;
    brainAiLimitHitRef.current = true;
    void trackAnalyticsEvent("ai_limit_hit", { surface: "chat_ai_brain_daily_cap", partner_user_id: partnerUserId });
  }, [isFreeTier, composerAiOpen, freeAiChatSuggestionsLeft, partnerUserId]);

  useEffect(() => {
    if (!isFreeTier) return;
    if (!composerAiOpen) return;
    if (freeAiChatSuggestionsLeft == null || freeAiChatSuggestionsLeft > 0) return;
    if (!softMonClaimOnce("ai_limit")) return;
    void trackAnalyticsEvent("ai_limit_conversion", {
      stage: "shown",
      surface: "chat_ai_brain_limit_card",
      partner_user_id: partnerUserId,
    });
  }, [isFreeTier, composerAiOpen, freeAiChatSuggestionsLeft, partnerUserId]);

  const runFetch = useCallback(
    async (opts: {
      regenerateVariant?: ChatBrainVariantKey | null;
      peer?: Record<ChatBrainVariantKey, string> | null;
      userAction?: boolean;
    }) => {
      if (!partnerUserId || disabled) return;
      const regenKey = opts.regenerateVariant || "all";
      const key = `${requestKeyBase}:${BRAIN_TAB}:${regenKey}`;

      const left = freeLeftRef.current;
      if (left != null && left <= 0) {
        setLoading(false);
        setPack(null);
        setError(null);
        return;
      }

      if (!isFreeTier && !opts.userAction && CHAT_BRAIN_SUGGESTIONS_CACHE.has(key)) {
        const cached = CHAT_BRAIN_SUGGESTIONS_CACHE.get(key)!;
        setPack(cached);
        return;
      }

      if (inFlightKeyRef.current === key && loading) return;

      if (!opts.userAction) {
        const now = Date.now();
        const elapsed = now - lastRequestAtRef.current;
        const minGap = 2600;
        if (elapsed < minGap) {
          if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
          debounceTimerRef.current = setTimeout(() => {
            void runFetch({ ...opts, userAction: false });
          }, minGap - elapsed);
          return;
        }
      }

      inFlightKeyRef.current = key;
      lastRequestAtRef.current = Date.now();
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;
      setLoading(true);
      setError(null);
      neyraAiLocaleRequestingSuggestions({ locale: lang, threadId: partnerUserId });
      neyraAiLocaleDevLog("requesting suggestions", { endpoint: "chat-brain/suggestions", locale: lang, partnerUserId });
      try {
        const strat = stageStrategyRef.current;
        const toneForRequest =
          overrideTone === "auto" && strat?.suggested_tone ? strat.suggested_tone : overrideTone || "auto";
        const res = await postChatBrainSuggestions({
          partnerUserId,
          mode: tabToRequestMode(BRAIN_TAB),
          tone: toneForRequest,
          language: lang,
          conversationMode: datingMode,
          isPremiumTier,
          aiCtx: {
            ...(aiCtx ?? {}),
            uiLocale: displayLocaleCode,
            overrideLanguage: overrideLanguage || null,
            overrideTone: overrideTone === "auto" ? null : (overrideTone as any),
          },
          regenerateVariant: opts.regenerateVariant ?? null,
          peerVariants: opts.peer ?? null,
          signal: ac.signal,
        });
        const m = res.meta;
        if (m?.suggested_tone && m?.suggested_conversation_mode) {
          stageStrategyRef.current = {
            suggested_tone: String(m.suggested_tone),
            suggested_conversation_mode: String(m.suggested_conversation_mode),
          };
        }
        if (!datingModeTouchedRef.current) {
          const dm = mapApiConversationModeToDatingMode(String(m?.suggested_conversation_mode || ""));
          if (dm) setDatingMode((prev) => (prev === dm ? prev : dm));
        }
        setPack(res);
        neyraAiLocaleDevLog("received suggestions", { endpoint: "chat-brain/suggestions", locale: lang, partnerUserId });
        neyraAiLocaleRenderedSuggestions({
          locale: lang,
          source: res.meta?.ai_used ? "ai" : "fallback",
        });
        if (!isFreeTier) {
          CHAT_BRAIN_SUGGESTIONS_CACHE.set(key, res);
          CHAT_BRAIN_LAST_GOOD_BY_PARTNER.set(partnerUserId, res);
        }
        if (isFreeTier) {
          incrementFreeAiChatSuggestionsUsed();
          bumpAiUsageMoment(1);
          onFreeAiChatConsumed?.();
        }
        const anyText = VARIANT_ORDER.some((k) => (res.variants[k] ?? "").trim());
        if (res.ui.suggestions_visible && !anyText) {
          setError(tRef.current("chat.brain.empty"));
        }
      } catch (e: unknown) {
        if (e instanceof Error && e.name === "AbortError") return;
        if (String((e as Error)?.message || "").toLowerCase().includes("abort")) return;
        const rateLimited = e instanceof RateLimitError;
        const em = e instanceof Error ? (e.message || "").trim() : "";
        const looksUnavailable =
          /\b503\b/i.test(em) || /unavailable|gemini_failed|ai_unavailable|service unavailable/i.test(em);
        const msg = rateLimited
          ? tRef.current("chat.brain.rateLimitedRetry")
          : looksUnavailable
            ? tRef.current("chat.brain.aiUnavailable")
            : em
              ? translateApiUserMessage(em, tRef.current)
              : tRef.current("chat.brain.error");
        setError(msg.trim() ? msg : tRef.current("chat.brain.error"));
        if (rateLimited) {
          setPack((prev) => {
            if (prev) return prev;
            const fromKey = CHAT_BRAIN_SUGGESTIONS_CACHE.get(key);
            const restored = fromKey ?? CHAT_BRAIN_LAST_GOOD_BY_PARTNER.get(partnerUserId) ?? null;
            if (restored) {
              CHAT_BRAIN_SUGGESTIONS_CACHE.set(key, restored);
            }
            return restored;
          });
        } else {
          setPack(null);
        }
      } finally {
        setLoading(false);
        if (inFlightKeyRef.current === key) inFlightKeyRef.current = "";
      }
    },
    [aiCtx, datingMode, disabled, displayLocaleCode, isFreeTier, isPremiumTier, lang, onFreeAiChatConsumed, overrideLanguage, overrideTone, partnerUserId],
  );

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
        debounceTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!partnerUserId || disabled) return;
    const key = `${requestKeyBase}:${BRAIN_TAB}:all`;
    if (isFreeTier) {
      setPack(null);
      return;
    }
    const cached = CHAT_BRAIN_SUGGESTIONS_CACHE.get(key);
    if (cached) {
      setPack(cached);
    } else {
      setPack(null);
    }
  }, [partnerUserId, disabled, requestKeyBase, isFreeTier]);

  useEffect(() => {
    if (!partnerUserId || disabled) return;
    const open = Boolean(composerAiOpen);
    const wasOpen = prevComposerAiOpenRef.current;
    prevComposerAiOpenRef.current = open;
    if (open && !wasOpen) {
      void runFetch({ userAction: false });
    }
  }, [composerAiOpen, disabled, partnerUserId, runFetch]);

  const onRegenerateAll = () => {
    void runFetch({ userAction: true });
  };

  useImperativeHandle(
    ref,
    () => ({
      regenerateAll: () => {
        if (!partnerUserId || disabled) return;
        void runFetch({ userAction: true });
      },
    }),
    [disabled, partnerUserId, runFetch],
  );

  /** Same chat + locale change: force a fresh chat-brain request (storage caches cleared globally). */
  const localeRefetchPartnerRef = useRef<number | null>(null);
  useEffect(() => {
    if (!partnerUserId || disabled) return;
    if (localeRefetchPartnerRef.current !== partnerUserId) {
      localeRefetchPartnerRef.current = partnerUserId;
      return;
    }
    if (isFreeTier) return;
    void runFetch({ userAction: true });
  }, [disabled, i18nLocale, isFreeTier, partnerUserId, runFetch]);

  const displayPack = useMemo((): ChatBrainSuggestionsResponse | null => {
    if (!pack) return null;
    if (!isFreeTier) return pack;
    return {
      ...pack,
      variants: {
        ...pack.variants,
        deep: "",
      },
    };
  }, [isFreeTier, pack]);

  const effectivePack = useMemo((): (ChatBrainSuggestionsResponse & { locale?: string; source?: string }) => {
    const p: any = displayPack;
    if (p) return p;
    return {
      ok: true,
      variants: {
        light: fb.easySuggestion,
        flirty: fb.flirtySuggestion,
        deep: fb.deepSuggestion,
      },
      coaching: { action: "write_now" },
      ui: { suggestions_visible: true },
      recommended_variant: "light",
      recommendation_reason: "invites_reply",
      variant_insights: {},
      meta: {
        mode: "auto",
        language: lang,
        regenerate_variant: null,
        ai_used: false,
      },
      locale: lang,
      source: "fallback",
    };
  }, [displayPack, fb.deepSuggestion, fb.easySuggestion, fb.flirtySuggestion, lang]);

  const useInComposer = (text: string, variant: ChatBrainVariantKey) => {
    const cleaned = String(text || "").trim();
    if (!cleaned) return;
    const wasRec = effectivePack?.recommended_variant === variant;
    void trackAnalyticsEvent("ai_suggestion_selected", {
      mode: tabToRequestMode(BRAIN_TAB),
      variant,
      partner_user_id: partnerUserId,
      language: lang,
      was_recommended: wasRec,
      coaching_action: effectivePack?.coaching?.action,
    });
    void (async () => {
      try {
        const { postAiMemoryEvent } = await import("../../../lib/chat/api");
        void postAiMemoryEvent({
          event_type: "cb_select",
          partner_user_id: partnerUserId ?? null,
          metadata_json: { variant, source: "chat_brain", was_recommended: wasRec },
        }).catch(() => {});
      } catch {
        // ignore
      }
    })();
    const pm = effectivePack?.meta;
    onInsertComposer(cleaned, {
      brain_mode: pm?.mode ?? String(tabToRequestMode(BRAIN_TAB)),
      variant,
      was_recommended: wasRec,
      conversation_stage: pm?.conversation_stage ?? pm?.relationship_stage ?? null,
      conversation_mode: pm?.conversation_mode ?? pm?.suggested_conversation_mode ?? null,
    });
  };

  const variantOrder = useMemo(() => {
    const rec = effectivePack?.recommended_variant;
    if (!rec) return VARIANT_ORDER;
    return [...VARIANT_ORDER].sort((a, b) => (a === rec ? -1 : b === rec ? 1 : 0));
  }, [effectivePack?.recommended_variant]);

  const blockedSet = useMemo(() => {
    const out = new Set<string>();
    for (const raw of blockedTexts || []) {
      const tx = String(raw || "").trim();
      if (tx) out.add(tx);
    }
    const draftLike = String((aiCtx as any)?.draft || "").trim();
    if (draftLike) out.add(draftLike);
    return out;
  }, [blockedTexts, aiCtx]);

  const primaryVariant = useMemo((): ChatBrainVariantKey | null => {
    if (!effectivePack) return null;
    for (const k of variantOrder) {
      const txt = (effectivePack.variants[k] ?? "").trim();
      if (txt && !blockedSet.has(txt)) return k;
    }
    return null;
  }, [blockedSet, effectivePack, variantOrder]);

  const primaryText = useMemo(() => {
    if (!effectivePack || !primaryVariant) return "";
    return (effectivePack.variants[primaryVariant] ?? "").trim();
  }, [effectivePack, primaryVariant]);

  const alternativeLines = useMemo(() => {
    if (!effectivePack || !primaryVariant) return [];
    const out: { key: ChatBrainVariantKey; text: string }[] = [];
    for (const k of VARIANT_ORDER) {
      if (k === primaryVariant) continue;
      const txt = (effectivePack.variants[k] ?? "").trim();
      if (txt && !blockedSet.has(txt)) out.push({ key: k, text: txt });
    }
    return out.slice(0, 3);
  }, [blockedSet, effectivePack, primaryVariant]);

  useEffect(() => {
    setShowMoreAlternatives(false);
  }, [partnerUserId, primaryVariant]);

  const showSuggestion =
    Boolean(effectivePack?.ui.suggestions_visible) &&
    !loading &&
    Boolean(primaryText) &&
    Boolean(primaryVariant) &&
    !(freeAiChatSuggestionsLeft != null && freeAiChatSuggestionsLeft <= 0);

  if (!partnerUserId) return null;

  const hasAlternatives = alternativeLines.length > 0;
  const coachScore = isPremiumTier ? effectivePack?.meta?.coach_score : null;

  return (
    <section
      className={["chat-brain-panel", "chat-brain-panel--simple", threadIsEmpty ? "chat-brain-panel--compact" : ""]
        .filter(Boolean)
        .join(" ")}
      aria-label={t("chat.brain.ariaPanel")}
    >
      <div className="chat-brain-panel__head chat-brain-panel__head--simple">
        <div className="chat-brain-panel__title">{t("chat.brain.wingmanTitle")}</div>
        <div className="caption" style={{ marginTop: 4, opacity: 0.82, lineHeight: 1.35 }}>
          {t("chat.brain.wingmanSubtitle")}
        </div>
        <div className="chat-brain-panel__modes" style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 8 }}>
          {(
            [
              ["easy", "chat.brain.mode.easy"],
              ["flirty", "chat.brain.mode.flirty"],
              ["funny", "chat.brain.mode.funny"],
              ["deep", "chat.brain.mode.deep"],
              ["confident", "chat.brain.mode.confident"],
              ["romantic", "chat.brain.mode.romantic"],
              ["playful", "chat.brain.mode.playful"],
              ["pickup_master", "chat.brain.mode.pickupMaster"],
            ] as const
          ).map(([id, labelKey]) => {
            const active = datingMode === id;
            const locked = id === "pickup_master" && !isPremiumTier;
            const inner = (
              <>
                {t(labelKey)}
                {locked ? " 🔒" : ""}
              </>
            );
            return locked ? (
              <Link
                key={id}
                href="/subscription?source=ai_pickup_master"
                className={`chip ${active ? "chat-brain-mode--active" : ""}`.trim()}
                style={{
                  padding: "8px 12px",
                  borderRadius: 999,
                  border: "1px solid rgba(255,255,255,0.12)",
                  background: "rgba(255,255,255,0.05)",
                  color: "inherit",
                  textDecoration: "none",
                  display: "inline-block",
                  fontSize: 13,
                  fontWeight: 650,
                  opacity: 0.75,
                }}
              >
                {inner}
              </Link>
            ) : (
              <button
                key={id}
                type="button"
                className={`chip ${active ? "chat-brain-mode--active" : ""}`.trim()}
                style={{
                  padding: "8px 12px",
                  borderRadius: 999,
                  border: active ? "1px solid rgba(124,92,255,0.55)" : "1px solid rgba(255,255,255,0.12)",
                  background: active ? "rgba(124,92,255,0.18)" : "rgba(255,255,255,0.05)",
                  color: "inherit",
                  cursor: "pointer",
                  fontSize: 13,
                  fontWeight: 650,
                }}
                disabled={disabled || loading}
                onClick={() => {
                  datingModeTouchedRef.current = true;
                  setDatingMode(id);
                  void runFetch({ userAction: true });
                }}
              >
                {inner}
              </button>
            );
          })}
        </div>
        {isPremiumTier &&
        effectivePack?.meta?.dating_strategy?.next_action === "suggest_meet" &&
        effectivePack?.ui?.suggestions_visible ? (
          <div
            className="caption chat-brain-panel__strategy-hint"
            style={{ marginTop: 8, opacity: 0.78, fontSize: 12, lineHeight: 1.35, fontStyle: "italic" }}
          >
            {t("chat.brain.strategySuggestMeet")}
          </div>
        ) : null}
        {coachScore ? (
          <div
            className="chat-brain-panel__coach"
            style={{
              marginTop: 10,
              padding: 12,
              border: "1px solid rgba(255,255,255,0.12)",
              background: "rgba(255,255,255,0.05)",
              borderRadius: 8,
              display: "grid",
              gap: 8,
            }}
          >
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <div>
                <div className="caption" style={{ opacity: 0.72 }}>Best move</div>
                <strong style={{ fontSize: 13 }}>{coachMoveLabel(coachScore.recommended_move)}</strong>
              </div>
              <div>
                <div className="caption" style={{ opacity: 0.72 }}>Risk</div>
                <strong style={{ fontSize: 13 }}>{riskLabel(coachScore.stall_risk)}</strong>
              </div>
              <div>
                <div className="caption" style={{ opacity: 0.72 }}>Meeting readiness</div>
                <strong style={{ fontSize: 13 }}>{readinessLabel(coachScore.meeting_readiness_meta)}</strong>
              </div>
              <div>
                <div className="caption" style={{ opacity: 0.72 }}>Score</div>
                <strong style={{ fontSize: 13 }}>{coachScore.momentum_score}/100</strong>
              </div>
            </div>
            <div>
              <div className="caption" style={{ opacity: 0.72 }}>Why this works</div>
              <div className="caption" style={{ opacity: 0.9, lineHeight: 1.4 }}>{coachScore.reason}</div>
            </div>
            {coachScore.casual_meeting_line ? (
              <button
                type="button"
                className="chat-brain-panel__btn"
                disabled={disabled}
                onClick={() => useInComposer(String(coachScore.casual_meeting_line || ""), "light")}
              >
                {coachScore.casual_meeting_line}
              </button>
            ) : null}
          </div>
        ) : null}
        {isPremiumTier ? (
          <div className="caption" style={{ marginTop: 8, opacity: 0.75, fontSize: 12, lineHeight: 1.35 }}>
            {t("chat.brain.premiumBrainHint")}
          </div>
        ) : (
          <div className="caption" style={{ marginTop: 8, opacity: 0.75, fontSize: 12, lineHeight: 1.35 }}>
            {t("chat.brain.freeBrainHint")}
          </div>
        )}
        {isFreeTier && freeAiChatSuggestionsLeft != null && freeAiChatSuggestionsLeft > 0 ? (
          <div className="caption chat-brain-panel__premium-hint" style={{ marginTop: 6, opacity: 0.78, lineHeight: 1.35 }}>
            {t("chat.ai.premium.freeRemainingLine", { count: freeAiChatSuggestionsLeft })}{" "}
            <Link className="chat-ai-inline__upgrade" href="/subscription?source=ai_chat_teaser">
              {fb.premiumCta}
            </Link>
          </div>
        ) : null}
      </div>

      <details className="chat-brain-panel__advanced">
        <summary className="chat-brain-panel__advanced-summary">{t("chat.brain.advancedSettings")}</summary>
        <div className="chat-brain-panel__advanced-body">
          <label className="sr-only" htmlFor="chat-ai-language-select">
            {t("chat.ai.lang.label")}
          </label>
          <select
            id="chat-ai-language-select"
            className="input"
            value={lang}
            onChange={(e) => setOverrideLanguage(String(e.target.value || "").trim())}
            disabled={disabled || loading}
          >
            {SUPPORTED_LOCALES.map((code) => (
              <option key={code} value={code}>
                {formatLocaleOptionLabel(code)}
              </option>
            ))}
          </select>
          <label className="sr-only" htmlFor="chat-ai-tone-select">
            {t("chat.ai.tone.label")}
          </label>
          <select
            id="chat-ai-tone-select"
            className="input"
            value={overrideTone}
            onChange={(e) => setOverrideTone(String(e.target.value || "auto") as ToneOption)}
            disabled={disabled || loading}
          >
            {(["auto", "playful", "confident", "warm", "flirty", "direct", "teasing", "thoughtful"] as ToneOption[]).map((tone) => (
              <option key={tone} value={tone}>
                {t(`chat.ai.tone.${tone}`)}
              </option>
            ))}
          </select>
        </div>
      </details>

      {error ? <div className="chat-brain-panel__error">{error}</div> : null}

      {isFreeTier && freeAiChatSuggestionsLeft != null && freeAiChatSuggestionsLeft <= 0 && composerAiOpen ? (
        <div className="chat-brain-panel__simple-card chat-brain-panel__simple-card--soft-mon" aria-live="polite">
          <p className="caption" style={{ margin: 0, opacity: 0.88, lineHeight: 1.45 }}>
            {t("chat.ai.premium.limitBody")}
          </p>
          <div style={{ marginTop: 12 }}>
            <Link
              className="btn btn-primary"
              href="/premium?source=ai_chat_brain_limit"
              onClick={() => {
                void trackAnalyticsEvent("ai_limit_conversion", {
                  stage: "cta_click",
                  surface: "chat_ai_brain_limit_cta",
                  partner_user_id: partnerUserId,
                });
                void trackAnalyticsEvent("paywall_clicked", { source: "ai_limit", surface: "chat_ai_brain_limit_cta" });
              }}
            >
              {t("chat.softMon.ctaContinue")}
            </Link>
          </div>
        </div>
      ) : null}

      {loading ? (
        <div className="chat-brain-panel__skeletons" aria-busy="true" aria-live="polite">
          <span className="sr-only">{t("chat.brain.loading")}</span>
          <div className="chat-brain-panel__skeleton chat-brain-panel__skeleton--single" />
        </div>
      ) : null}

      {effectivePack?.ui.suggestions_visible && !(isFreeTier && freeAiChatSuggestionsLeft != null && freeAiChatSuggestionsLeft <= 0) ? (
        <div className="chat-brain-panel__simple-card">
          {!threadIsEmpty ? (
            <div className="caption" style={{ marginTop: 2, opacity: 0.82, lineHeight: 1.35 }}>
              {fb.panelSubtitle}
            </div>
          ) : null}
          <div className="chat-brain-panel__simple-actions" style={{ marginTop: 10, marginBottom: 12 }}>
            <button type="button" className="chat-brain-panel__btn" disabled={disabled || loading} onClick={onRegenerateAll}>
              {fb.regenerateButton}
            </button>
          </div>

          {(["light", "flirty", "deep"] as ChatBrainVariantKey[]).map((variant) => {
            const text =
              (effectivePack?.variants?.[variant] ?? "").trim() ||
              (variant === "light" ? fb.easySuggestion : variant === "flirty" ? fb.flirtySuggestion : fb.deepSuggestion);
            const label = variant === "light" ? fb.easyLabel : variant === "flirty" ? fb.flirtyLabel : fb.deepLabel;
            const desc = variant === "light" ? fb.easyDescription : variant === "flirty" ? fb.flirtyDescription : fb.deepDescription;
            if (!text) return null;
            return (
              <div key={variant} className="chat-brain-panel__alt-row" role="listitem" style={{ display: "block" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "baseline" }}>
                  <strong style={{ fontSize: 13, opacity: 0.9 }}>{label}</strong>
                  {variant === effectivePack?.recommended_variant ? <div className="chat-ai-inline__best-pill">{t("chat.brain.best")}</div> : null}
                </div>
                <div className="chat-brain-panel__alt-text" style={{ marginTop: 6 }}>{text}</div>
                <div className="caption" style={{ marginTop: 6, opacity: 0.78 }}>{desc}</div>
                <div className="chat-brain-panel__simple-actions" style={{ marginTop: 10 }}>
                  <button type="button" className="chat-brain-panel__btn chat-brain-panel__btn--primary" disabled={disabled} onClick={() => useInComposer(text, variant)}>
                    {fb.sendButton}
                  </button>
                  <button type="button" className="chat-brain-panel__btn" disabled={disabled} onClick={() => useInComposer(text, variant)}>
                    {fb.editButton}
                  </button>
                  <button
                    type="button"
                    className="chat-brain-panel__btn"
                    disabled={disabled || loading}
                    onClick={() => {
                      void runFetch({
                        userAction: true,
                        regenerateVariant: variant,
                        peer: (effectivePack?.variants ?? null) as any,
                      });
                    }}
                  >
                    {fb.moreButton}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      ) : !loading && effectivePack?.ui.suggestions_visible && !(isFreeTier && freeAiChatSuggestionsLeft != null && freeAiChatSuggestionsLeft <= 0) ? (
        <div className="chat-brain-panel__simple-empty">
          <button type="button" className="chat-brain-panel__regen-all" disabled={disabled} onClick={onRegenerateAll}>
            {t("chat.brain.differentIdea")}
          </button>
        </div>
      ) : null}
    </section>
  );
});
