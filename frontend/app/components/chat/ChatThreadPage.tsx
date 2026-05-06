"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useChatThreadController } from "../../../lib/chat/useChatThreadController";
import { conversationContext } from "../../../lib/chat/normalize";
import { isRawI18nText, resolveI18nText } from "../../../lib/i18n/message";
import type { ReportCategory } from "../../../lib/safety/api";
import { useT } from "../i18n/I18nProvider";
import { inspectI18nText, renderDebugText } from "../i18n/debugText";
import { AiDebugPill } from "../AiDebugPill";
import { PageShell } from "../PageShell";
import { RuntimeErrorBoundary } from "../RuntimeErrorBoundary";
import { Button, Chip } from "../ui";
import { ChatComposer } from "./ChatComposer";
import { ChatEmptyState } from "./ChatEmptyState";
import { ChatHeader } from "./ChatHeader";
import { ChatThreadOverflowMenu } from "./ChatThreadOverflowMenu";
import { ChatMessageList } from "./ChatMessageList";
import { ChatAiSuccessNudge } from "./ChatAiSuccessNudge";
import { ChatSendMicroFeedback } from "./ChatSendMicroFeedback";
import { ViralInviteNudge, shouldShowViralInviteAfterReply } from "./ViralInviteNudge";
import { ChatAiBrainPanel, type ChatAiBrainPanelHandle } from "./ChatAiBrainPanel";
import { ChatOpenerQuickBar } from "./ChatOpenerQuickBar";
import { ViralShareModal } from "./ViralShareModal";
import { ChatFirstMessageSuggestion } from "./ChatFirstMessageSuggestion";
import { ChatMeetingSuggestInline } from "./ChatMeetingSuggestInline";
import { ChatNextStepInline } from "./ChatNextStepInline";
import { ChatReplySuggestionsInline } from "./ChatReplySuggestionsInline";
import { ChatReviveSuggestionsInline } from "./ChatReviveSuggestionsInline";
import { ChatMomentumDateCoach } from "./ChatMomentumDateCoach";
import { ViralMomentShareModal } from "../ViralMomentShareModal";
import { ReviewPromptSheet } from "../ReviewPromptSheet";
import { ChatAiBar } from "./ChatAiBar";
import {
  bumpAiBrainInsertSessionCount,
  bumpLifetimeSuccessChats,
  getAiBrainInsertSessionCount,
  markReviewPromptShownThisSession,
  markReviewPromptShownTimestamp,
  markReviewSessionChatError,
  markReviewSessionRealAiUsed,
  shouldOfferSmartReviewPrompt,
  type SmartReviewTrigger,
} from "../../../lib/reviewPrompt";
import { utcDayKey } from "../../../lib/retention/dedupe";
import { softMonClaimOnce } from "../../../lib/monetization/softMonSession";
import { ChatCoachBar, type CoachLevel, type CoachState } from "./ChatCoachBar";
import {
  draftStateFromDraft,
  threadStateFromMessages,
  trackAiAssistDismissed,
  trackAiAssistEditedAfterInsert,
  trackAiAssistRequested,
  trackAiAssistSentAfterUse,
  type AiAssistMode,
} from "../../../lib/chat/aiAssistAnalytics";
import { apiFetch } from "../../../lib/api";
import { setPaywallConversionHint } from "../../../lib/paywallConversionHint";
import { AI_DEBUG_ENABLED, FORCE_AI_VISIBLE, logAiGate } from "../../../lib/aiDebug";
import { FREE_AI_CHAT_SUGGESTIONS_PER_DAY, getFreeAiChatSuggestionsLeftToday } from "../../../lib/chat/aiChatUsage";
import { fetchDailyBoosts } from "../../../lib/dailyBoosts";
import { resolveAiTier } from "../../../lib/chat/aiTier";
import type { ChatBrainMode, ChatBrainVariantKey, MessageAssistMeta } from "../../../lib/chat/api";
import { fetchAiCoach, fetchReadinessScore } from "../../../lib/chat/api";
import { messageFeelsEngagingHeuristic } from "../../../lib/chat/messageEngagement";
import { getStoredLocale } from "../../../lib/i18n";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { fetchAbCopy, trackAbMetric, type AbCopyMap } from "../../../lib/abCopy";
import { trackPremiumPlusHookClicked, trackPremiumPlusHookSeen } from "../../../lib/premiumPlusHooks";
import { buildSubscriptionHref, getPremiumPlusHookVariant, maybeEmitHookConverted, trackPremiumPlusHookVariant } from "../../../lib/premiumPlusHookOptimization";
import type { ConversationState } from "../../../lib/chat/aiLanguageTone";
import type { AiOpenerMatchContext } from "../../../lib/chat/api";
import { canOfferViralSharePrompt, incrementViralSharePromptSessionCount } from "../../../lib/viralShareSession";
import { isStrongAiForViral, type ViralAiInsertion } from "../../../lib/viralStrongCandidate";
import { ViralShareInlineBar, trackViralShareClicked } from "./ViralShareInlineBar";

const COACH_HIDDEN_KEY = "neyra:coach:hidden";

function lastPartnerMessageFromThread(messages: unknown[], partnerUserId: number | null): string {
  if (partnerUserId == null) return "";
  const pid = Number(partnerUserId);
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i] as { senderId?: unknown; content?: unknown };
    if (Number(m.senderId) === pid) return String(m.content || "").trim();
  }
  return "";
}

type HealthState = "strong" | "building" | "needs";
type HealthPack = {
  state: HealthState;
  feedback: string;
  why: string[];
  tryTip: string;
  score: number;
};

function clamp(n: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, n));
}

function isPositiveTone(text: string): boolean {
  const s = (text || "").toLowerCase();
  if (!s.trim()) return false;
  return (
    s.includes("😊") ||
    s.includes("😄") ||
    s.includes("😂") ||
    s.includes("❤️") ||
    s.includes("😍") ||
    s.includes("😉") ||
    s.includes("!") ||
    /\b(nice|love|cool|amazing|great|haha|lol|клас|круто|супер|ха-ха|лол)\b/i.test(s)
  );
}

function computeHealthPack(input: {
  messages: any[];
  viewerId: number | null;
  partnerId: number | null;
  prevScore: number;
  t: (k: string, v?: any) => string;
}): HealthPack | null {
  const { messages, viewerId, partnerId, prevScore, t } = input;
  if (!viewerId || !partnerId) return null;
  const rows = (messages || [])
    .slice(-40)
    .map((m) => {
      const sender = Number((m as any)?.senderId);
      const role = sender === Number(viewerId) ? "me" : sender === Number(partnerId) ? "them" : null;
      const text = String((m as any)?.content || "").trim();
      const tsRaw = String((m as any)?.timestamp ?? (m as any)?.createdAt ?? "").trim();
      const ms = tsRaw ? Date.parse(tsRaw) : NaN;
      return role && text ? { role, text, ms: Number.isFinite(ms) ? ms : null } : null;
    })
    .filter(Boolean) as { role: "me" | "them"; text: string; ms: number | null }[];

  if (rows.length < 4) return null;

  const lastThem = [...rows].reverse().find((r) => r.role === "them")?.text || "";
  const lastMe = [...rows].reverse().find((r) => r.role === "me")?.text || "";

  const recent = rows.slice(-12);
  const meCount = recent.filter((r) => r.role === "me").length;
  const themCount = recent.filter((r) => r.role === "them").length;
  const balance = meCount && themCount ? 1 - Math.abs(meCount - themCount) / (meCount + themCount) : 0.5;

  const meQuestions = recent.filter((r) => r.role === "me" && r.text.includes("?")).length;
  const themQuestions = recent.filter((r) => r.role === "them" && r.text.includes("?")).length;
  const engagement = clamp((meQuestions + themQuestions) / 4, 0, 1);

  const tonePos = isPositiveTone(lastThem) || isPositiveTone(lastMe);
  const tone = tonePos ? 1 : 0.45;

  // Response speed: average time between turn switches (cap at 6h).
  let deltas: number[] = [];
  for (let i = 1; i < recent.length; i += 1) {
    const a = recent[i - 1];
    const b = recent[i];
    if (!a.ms || !b.ms) continue;
    if (a.role === b.role) continue;
    const d = clamp((b.ms - a.ms) / 60000, 0, 360);
    deltas.push(d);
  }
  const avgMin = deltas.length ? deltas.reduce((x, y) => x + y, 0) / deltas.length : 60;
  const speed = avgMin <= 8 ? 1 : avgMin <= 25 ? 0.75 : avgMin <= 90 ? 0.55 : 0.35;

  const lenMe = recent.filter((r) => r.role === "me").map((r) => r.text.length);
  const lenThem = recent.filter((r) => r.role === "them").map((r) => r.text.length);
  const avgLenMe = lenMe.length ? lenMe.reduce((x, y) => x + y, 0) / lenMe.length : 0;
  const avgLenThem = lenThem.length ? lenThem.reduce((x, y) => x + y, 0) / lenThem.length : 0;
  const depth = clamp(Math.min(avgLenMe, avgLenThem) / 120, 0, 1);

  const raw = 0.28 * speed + 0.26 * engagement + 0.22 * balance + 0.14 * tone + 0.10 * depth;
  const smoothed = clamp(prevScore * 0.72 + raw * 0.28, 0, 1);

  let state: HealthState = "building";
  if (smoothed >= 0.72) state = "strong";
  else if (smoothed <= 0.42) state = "needs";

  const why: string[] = [];
  why.push(speed >= 0.75 ? t("chat.health.why.speed.good") : t("chat.health.why.speed.slow"));
  why.push(engagement >= 0.6 ? t("chat.health.why.engagement.good") : t("chat.health.why.engagement.more"));
  why.push(balance >= 0.65 ? t("chat.health.why.balance.good") : t("chat.health.why.balance.off"));
  const whyShort = why.slice(0, 3);

  let tryTip = t("chat.health.try.lightQuestion");
  if (state === "needs") tryTip = t("chat.health.try.morePersonal");
  if (state === "strong") tryTip = t("chat.health.try.nextStep");
  else if (tonePos && state === "building") tryTip = t("chat.health.try.playful");

  const feedback =
    state === "strong" ? t("chat.health.feedback.niceFlow") : state === "needs" ? t("chat.health.feedback.improving") : t("chat.health.feedback.gettingStronger");

  return { state, feedback, why: whyShort, tryTip, score: smoothed };
}

export function ChatThreadPage() {
  const router = useRouter();
  const c = useChatThreadController();
  const messagesLiveRef = useRef(c.messages);
  messagesLiveRef.current = c.messages;
  const draftLiveRef = useRef(c.draft);
  draftLiveRef.current = c.draft ?? "";
  const reviveTimerRef = useRef<number | null>(null);
  const { t, locale: uiLocaleTag } = useT("ChatThreadPage");
  const searchParams = useSearchParams();
  const autoFocusComposer = (searchParams?.get("focus") ?? "") === "1";
  const prefillDraft = String(searchParams?.get("draft") ?? "").trim();
  const wantQuickSendBar = (searchParams?.get("quick_send") ?? "") === "1";
  const toolbarAria = inspectI18nText(t("chat.thread.toolbarAria"), { component: "ChatThreadPage", prop: "toolbarAria" });
  const loadErrorText = resolveI18nText(c.loadError, t);
  const sendErrorText = resolveI18nText(c.sendError, t);
  const [aiOpen, setAiOpen] = useState(false);
  const [sendUiLocked, setSendUiLocked] = useState(false);
  const [planCode, setPlanCode] = useState<string>("");
  const aiTier = resolveAiTier({ isPremium: Boolean(c.viewer?.isPremium), planCode });
  const [aiChatUsageEpoch, setAiChatUsageEpoch] = useState(0);
  const [streakBonusAiChat, setStreakBonusAiChat] = useState(0);
  const [sendSuccessBurstKey, setSendSuccessBurstKey] = useState(0);
  const [partnerReplyGlowId, setPartnerReplyGlowId] = useState<string | null>(null);
  const prevThreadMsgCountRef = useRef(0);
  const prevOutboundForMatchRef = useRef(-1);

  useEffect(() => {
    if (!c.viewer?.userId) return;
    let cancelled = false;
    void fetchDailyBoosts().then((b) => {
      if (cancelled || !b) return;
      setStreakBonusAiChat(Math.max(0, Math.trunc(Number(b.streak_bonus_ai_chat ?? 0))));
    });
    return () => {
      cancelled = true;
    };
  }, [c.viewer?.userId, aiChatUsageEpoch]);

  const freeAiChatCap = FREE_AI_CHAT_SUGGESTIONS_PER_DAY + streakBonusAiChat;
  const freeAiChatSuggestionsLeft = useMemo(
    () => (aiTier === "free" ? getFreeAiChatSuggestionsLeftToday(freeAiChatCap) : null),
    [aiChatUsageEpoch, aiTier, freeAiChatCap],
  );

  const chatOpenedForPartnerRef = useRef<number | null>(null);
  useEffect(() => {
    const pid = c.partnerUserId != null ? Number(c.partnerUserId) : null;
    if (!pid || pid <= 0) return;
    if (chatOpenedForPartnerRef.current === pid) return;
    chatOpenedForPartnerRef.current = pid;
    void trackAnalyticsEvent("chat_opened", { source: "chat", partner_user_id: pid });
  }, [c.partnerUserId]);

  const retentionReopenEmittedRef = useRef<number | null>(null);
  const retentionMomentumShownRef = useRef(false);

  useEffect(() => {
    retentionReopenEmittedRef.current = null;
    retentionMomentumShownRef.current = false;
  }, [c.partnerUserId]);

  useEffect(() => {
    const msgs = c.messages || [];
    const n = msgs.length;
    const prev = prevThreadMsgCountRef.current;
    prevThreadMsgCountRef.current = n;
    if (n <= prev || c.partnerUserId == null) return;
    const last = msgs[n - 1];
    if (!last) return;
    if (Number(last.senderId) !== Number(c.partnerUserId)) return;
    const id = String(last.id ?? "").trim();
    if (!id) return;
    setPartnerReplyGlowId(id);
    const tm = window.setTimeout(() => {
      setPartnerReplyGlowId((cur) => (cur === id ? null : cur));
    }, 2600);
    return () => window.clearTimeout(tm);
  }, [c.messages, c.partnerUserId]);

  useEffect(() => {
    if (!c.viewer?.userId) return;
    void fetchAbCopy(["chat.opener.nudge", "paywall.message"]).then(setAbCopy);
  }, [c.viewer?.userId]);
  const isDemoChat = Boolean(c.partner?.isDemoProfile);
  const aiPanelOpen = aiOpen;
  const readiness: null = null;
  const coach: null = null;
  const fromMatchRef = useRef(false);
  const promptShownRef = useRef(false);
  const openerUsedAfterMatchRef = useRef(false);
  const firstMessageSentTrackedRef = useRef(false);
  const firstReplyReceivedTrackedRef = useRef(false);
  const firstMessageAiAssistedTrackedRef = useRef(false);
  const firstOutgoingAtRef = useRef<number>(0);
  const followupSuggestedTrackedRef = useRef(false);
  const noFirstMessageNudgeRef = useRef(false);
  const strongerNoReplyNudgeRef = useRef(false);
  const plusHookSeenRef = useRef<{ recovery?: boolean; escalation?: boolean }>({});
  const [successNudge, setSuccessNudge] = useState<{
    message: string;
    ctaHref?: string | null;
    ctaLabel?: string | null;
    ctaPreventNavigation?: boolean;
    onCtaClick?: (() => void) | null;
    ttlMs?: number;
    appearance?: "default" | "soft";
  } | null>(null);

  const sendLockRef = useRef(false);
  const lastSendAttemptAtRef = useRef(0);
  const quickSendTriggeredRef = useRef(false);

  function hashDraftForKey(input: string): string {
    // Small stable hash for idempotency keys (not crypto).
    const s = String(input || "");
    let h = 5381;
    for (let i = 0; i < s.length; i += 1) h = ((h << 5) + h) ^ s.charCodeAt(i);
    return (h >>> 0).toString(16);
  }

  function markUiSendingLocked(locked: boolean) {
    sendLockRef.current = locked;
    setSendUiLocked(locked);
  }

  function cleanQuickSendUrl() {
    try {
      const params = new URLSearchParams(searchParams?.toString() || "");
      params.delete("quick_send");
      params.delete("draft");
      const base = `/chat/${encodeURIComponent(String(c.partnerUserId ?? ""))}`;
      const qs = params.toString();
      router.replace(qs ? `${base}?${qs}` : base);
    } catch {
      // ignore
    }
  }
  const [sendMicroFeedbackKey, setSendMicroFeedbackKey] = useState(0);
  const dismissSendMicroFeedback = useCallback(() => {
    setSendMicroFeedbackKey(0);
  }, []);
  const [abCopy, setAbCopy] = useState<AbCopyMap>({});
  const abCopyRef = useRef<AbCopyMap>({});
  abCopyRef.current = abCopy;
  const conversionWarnedHashRef = useRef<string>("");
  const conversionUsedRewriteRef = useRef(false);
  const matchMomentBannerShownRef = useRef(false);
  const aiAssistPaywallTimeoutRef = useRef<number | null>(null);
  const aiAssistSentAtRef = useRef<number>(0);
  const aiAssistSentFiredRef = useRef<number>(0);
  const recoveryUsedAtRef = useRef<number>(0);
  const recoverySuccessFiredRef = useRef<number>(0);
  const escalationUsedAtRef = useRef<number>(0);
  const escalationSuccessFiredRef = useRef<number>(0);
  const lastReadinessLevelRef = useRef<"low" | "medium" | "high" | null>(null);
  const readinessSuccessFiredRef = useRef<number>(0);
  const demoChatStartedTrackedRef = useRef<number | null>(null);

  const [viralInviteVisible, setViralInviteVisible] = useState(false);

  const [coachHidden, setCoachHidden] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    try {
      return (localStorage.getItem(COACH_HIDDEN_KEY) || "") === "1";
    } catch {
      return false;
    }
  });
  const [coachTip, setCoachTip] = useState<{ state: CoachState; level: CoachLevel; message: string; actions: { type: any; label: string }[] } | null>(null);
  const coachLastShownAtRef = useRef<number>(0);
  const coachLastSigRef = useRef<string>("");
  const coachLastTriggerRef = useRef<string>("");
  const coachLastIncomingIdRef = useRef<string>("");
  const coachInFlightRef = useRef<boolean>(false);
  const coachInactivityTimerRef = useRef<number | null>(null);
  const coachLastInteractionAtRef = useRef<number>(Date.now());
  const [health, setHealth] = useState<HealthPack | null>(null);
  const healthScoreRef = useRef<number>(0.55);
  const goodConversation = health?.state === "strong";

  const conversationState: ConversationState = useMemo(() => {
    const msgs = c.messages || [];
    if (msgs.length <= 1) return "new";
    const last = msgs.slice(-1)[0];
    const ts = Date.parse(String(last?.timestamp ?? last?.createdAt ?? "").trim());
    const ageMin = Number.isFinite(ts) ? Math.max(0, Math.round((Date.now() - ts) / 60000)) : 0;
    if (ageMin >= 24 * 60) return "dead";
    return "active";
  }, [c.messages]);

  const aiCtx = useMemo(
    () => ({
      viewer: c.viewer ? { nativeLanguage: (c.viewer as any).nativeLanguage ?? null, additionalLanguages: (c.viewer as any).additionalLanguages ?? [] } : null,
      partner: c.partner ? { nativeLanguage: (c.partner as any).nativeLanguage ?? null, additionalLanguages: (c.partner as any).additionalLanguages ?? [] } : null,
      uiLocale: uiLocaleTag,
      conversationState,
      isFirstMessage: (c.messages || []).length === 0,
    }),
    [c.messages, c.partner, c.viewer, conversationState, uiLocaleTag],
  );

  /** Monetization nudges are limited to session-scoped partner-reply / match / AI-limit hints only. */
  const scheduleAiAssistPaywall = useCallback(() => {}, []);

  useEffect(() => {
    return () => {
      if (aiAssistPaywallTimeoutRef.current != null && typeof window !== "undefined") {
        window.clearTimeout(aiAssistPaywallTimeoutRef.current);
        aiAssistPaywallTimeoutRef.current = null;
      }
    };
  }, [c.partnerUserId]);

  useEffect(() => {
    setViralInviteVisible(false);
  }, [c.partnerUserId]);

  useEffect(() => {
    setSendMicroFeedbackKey(0);
  }, [c.partnerUserId]);

  useEffect(() => {
    if (!brainLastSentAtRef.current) return;
    if (!c.partnerUserId) return;
    const last = c.messages.length ? c.messages[c.messages.length - 1] : null;
    if (!last) return;
    if (Number(last.senderId) !== Number(c.partnerUserId)) return;
    const sentAt = brainLastSentAtRef.current;
    brainLastSentAtRef.current = null;
    const meta = brainLastMetaRef.current;
    brainLastMetaRef.current = null;
    const delayMin = sentAt ? Math.max(0, Math.round((Date.now() - sentAt) / 60000)) : null;
    void trackAnalyticsEvent("ai_suggestion_partner_replied", {
      partner_user_id: c.partnerUserId,
      reply_delay_minutes: delayMin,
      variant: meta?.variant,
      was_recommended: meta?.was_recommended,
      brain_mode: meta?.brain_mode,
    });
    void (async () => {
      try {
        const { postAiMemoryEvent } = await import("../../../lib/chat/api");
        void postAiMemoryEvent({
          event_type: "partner_replied",
          partner_user_id: Number(c.partnerUserId),
          metadata_json: {
            reply_delay_minutes: delayMin,
            previous_style: meta?.variant,
            previous_source: "chat_brain",
            was_recommended: meta?.was_recommended,
          },
        }).catch(() => {});
        void postAiMemoryEvent({
          event_type: "cb_reply",
          partner_user_id: Number(c.partnerUserId),
          metadata_json: {
            variant: meta?.variant,
            reply_delay_minutes: delayMin,
            was_recommended: meta?.was_recommended,
          },
        }).catch(() => {});
      } catch {
        // ignore
      }
    })();
  }, [c.messages, c.messages.length, c.partnerUserId]);

  const trialBanner = useMemo(() => {
    const v = c.viewer;
    if (!v) return null;
    const until = (v.premiumUntil || "").trim();
    const isTrial = Boolean(v.isTrialUsed ?? v.isTrial);
    const daysLeft = v.trialDaysLeft;
    if (!isTrial) return null;
    // Active trial window
    if (until && Number.isFinite(daysLeft as any) && (daysLeft as number) > 0) {
      return {
        kind: "active" as const,
        text: t("chat.trial.activeTitle"),
        sub: t("chat.trial.activeSub", { days: daysLeft as number }),
      };
    }
    // Expired trial
    if (until && (daysLeft == null || (Number.isFinite(daysLeft as any) && (daysLeft as number) <= 0))) {
      return {
        kind: "expired" as const,
        text: t("chat.trial.expiredTitle"),
        sub: null,
      };
    }
    return null;
  }, [c.viewer, t]);

  const maybeShowSuccessNudge = useCallback(
    (message: string, options: { allowPlusTieIn: boolean }) => {
      const base = (message ?? "").trim();
      if (!base) return;
      const showPlus = options.allowPlusTieIn && aiTier !== "premium_plus";
      if (showPlus) {
        try {
          const key = "ai_success_plus_upsell_shown";
          if (sessionStorage.getItem(key) === "1") {
            setSuccessNudge({ message: base });
            return;
          }
          sessionStorage.setItem(key, "1");
        } catch {
          // ignore
        }
        setSuccessNudge({
          message: `${base} ${t("chat.success.plusGoesDeeper")}`.trim(),
          ctaHref: "/subscription",
          ctaLabel: t("common.upgrade"),
        });
        return;
      }
      setSuccessNudge({ message: base });
    },
    [aiTier, t],
  );

  useEffect(() => {
    if (!isDemoChat || !c.partnerUserId) return;
    if (demoChatStartedTrackedRef.current === c.partnerUserId) return;
    demoChatStartedTrackedRef.current = c.partnerUserId;
    void trackAnalyticsEvent("demo_chat_started", { partner_user_id: c.partnerUserId, surface: "chat_thread" });
  }, [c.partnerUserId, isDemoChat]);

  const trackDemoAiSuggestionUsed = useCallback(
    (source: string) => {
      if (!isDemoChat) return;
      void trackAnalyticsEvent("ai_suggestion_used_in_demo", { partner_user_id: c.partnerUserId, source });
    },
    [c.partnerUserId, isDemoChat],
  );

  useEffect(() => {
    // Success heuristic 1: partner replies after an AI-assisted send.
    if (isDemoChat) return;
    const sentAt = aiAssistSentAtRef.current;
    if (!sentAt) return;
    if (aiAssistSentFiredRef.current === sentAt) return;
    const viewerId = c.viewer?.userId ?? null;
    if (viewerId == null) return;
    const partnerId = c.partnerUserId ?? null;
    if (partnerId == null) return;
    const last = (c.messages || []).slice(-1)[0];
    if (!last) return;
    const isFromPartner = last.senderId === partnerId;
    const ts = Date.parse((last.timestamp ?? last.createdAt ?? "").trim());
    if (!isFromPartner || !Number.isFinite(ts)) return;
    // Window: 6 hours after the assist send (grounded but forgiving).
    if (ts < sentAt || ts - sentAt > 6 * 60 * 60 * 1000) return;
    aiAssistSentFiredRef.current = sentAt;
    bumpLifetimeSuccessChats();
    void trackAnalyticsEvent("ai_assist_success_reply_received", {
      plan_tier: aiTier,
      thread_state: threadStateFromMessages(c.messages.length),
    });
    const moved = t("chat.success.movedForward");
    const msg =
      aiTier === "free" ? `${moved} ${t("growth.ai.socialProofReplies")}`.trim() : moved;
    maybeShowSuccessNudge(msg, { allowPlusTieIn: true });
    window.setTimeout(() => {
      scheduleSmartReviewRef.current({ trigger: "partner_reply_ai", firstMessageJustSent: false });
    }, 2800);
  }, [aiTier, c.messages, c.partnerUserId, c.viewer?.userId, isDemoChat, maybeShowSuccessNudge, t]);

  useEffect(() => {
    // First reply received after the first outgoing message in a new thread.
    const sentAt = firstOutgoingAtRef.current;
    if (!sentAt) return;
    if (firstReplyReceivedTrackedRef.current) return;
    const partnerId = c.partnerUserId ?? null;
    if (partnerId == null) return;
    const last = (c.messages || []).slice(-1)[0];
    if (!last) return;
    if (last.senderId !== partnerId) return;
    const ts = Date.parse((last.timestamp ?? last.createdAt ?? "").trim());
    if (!Number.isFinite(ts) || ts < sentAt) return;
    firstReplyReceivedTrackedRef.current = true;
    if (conversionWarnedHashRef.current) {
      void trackAnalyticsEvent("conversion_reply_received", {
        partner_user_id: partnerId,
        used_rewrite: Boolean(conversionUsedRewriteRef.current),
        plan_tier: aiTier,
      });
      conversionWarnedHashRef.current = "";
      conversionUsedRewriteRef.current = false;
    }
    void trackAnalyticsEvent("first_reply_received", {
      plan_tier: aiTier,
      source: fromMatchRef.current ? "match_moment" : "chat_thread",
    });

    const openerVid = abCopyRef.current["chat.opener.nudge"]?.variant_id ?? "";
    if (openerVid) {
      trackAbMetric("reply", "chat.opener.nudge", openerVid);
    }

    const showPartnerUpsell = aiTier === "free" && softMonClaimOnce("partner_reply");
    if (showPartnerUpsell) {
      setPaywallConversionHint("after_reply");
      void trackAnalyticsEvent("conversion_after_reply", {
        stage: "shown",
        surface: "partner_reply_banner",
        plan_tier: aiTier,
        partner_user_id: partnerId,
      });
      setSuccessNudge({
        message: t("chat.partnerReply.banner"),
        ctaHref: "/premium?source=partner_reply_upsell",
        ctaLabel: t("chat.softMon.ctaContinue"),
        ttlMs: 18_000,
        appearance: "soft",
        onCtaClick: () => {
          void trackAnalyticsEvent("conversion_after_reply", {
            stage: "cta_click",
            surface: "partner_reply_banner",
            plan_tier: aiTier,
            partner_user_id: partnerId,
          });
          void trackAnalyticsEvent("paywall_cta_clicked", {
            cta_label: "continue",
            surface: "partner_reply_banner",
            plan_tier: aiTier,
          });
        },
      });
      void trackAnalyticsEvent("paywall_shown", {
        surface: "partner_reply_banner",
        plan_tier: aiTier,
        partner_user_id: partnerId,
      });
    } else {
      maybeShowSuccessNudge(t("chat.firstMessage.replyNudge"), { allowPlusTieIn: false });
    }

    if (!isDemoChat && shouldShowViralInviteAfterReply()) {
      const tmr = window.setTimeout(() => {
        setViralInviteVisible(true);
        void trackAnalyticsEvent("viral_invite_nudge_shown", { source: "chat_after_reply" });
      }, 9000);
      return () => window.clearTimeout(tmr);
    }
    return undefined;
  }, [aiTier, c.messages, c.partnerUserId, maybeShowSuccessNudge, t, isDemoChat]);

  useEffect(() => {
    // Light nudge 1–3 min after a fresh match thread with no first message.
    if (noFirstMessageNudgeRef.current) return;
    if (!c.canCompose) return;
    if (c.messages.length !== 0) return;
    if ((c.draft ?? "").trim()) return;
    const matchId = c.matchId ?? null;
    if (!matchId) return;

    const isDev = typeof process !== "undefined" && process.env.NODE_ENV === "development";
    const delayMs = isDev ? 10_000 + Math.floor(Math.random() * 10_000) : 60_000 + Math.floor(Math.random() * 120_000);
    const handle = window.setTimeout(() => {
      if (c.messages.length !== 0) return;
      if ((draftLiveRef.current ?? "").trim()) return;
      noFirstMessageNudgeRef.current = true;
      void trackAnalyticsEvent("nudge_no_first_message_shown", { match_id: matchId, partner_user_id: c.partnerUserId ?? null });
      setAiOpen(true);
      const say = abCopyRef.current["chat.opener.nudge"]?.text?.trim()
        ? abCopyRef.current["chat.opener.nudge"]!.text
        : t("chat.nudge.sayHi");
      setSuccessNudge({ message: say, ttlMs: 10_000 });
    }, delayMs);
    return () => window.clearTimeout(handle);
  }, [abCopy, c.canCompose, c.draft, c.matchId, c.messages.length, c.partnerUserId, t]);

  useEffect(() => {
    // Follow-up suggestion if partner hasn't replied after a calm delay.
    const sentAt = firstOutgoingAtRef.current;
    if (!sentAt) return;
    if (firstReplyReceivedTrackedRef.current) return;
    if (followupSuggestedTrackedRef.current) return;
    if (!c.canCompose) return;

    // Delay: 1–3 minutes (prod). Dev uses a short window for QA.
    const isDev = typeof process !== "undefined" && process.env.NODE_ENV === "development";
    const delayMs = isDev ? 12_000 + Math.floor(Math.random() * 18_000) : 60_000 + Math.floor(Math.random() * 120_000);
    const handle = window.setTimeout(() => {
      if (firstReplyReceivedTrackedRef.current) return;
      // Only if thread still looks like "one-sided start".
      const partnerId = c.partnerUserId ?? null;
      if (partnerId == null) return;
      const msgs = c.messages || [];
      const hasPartnerReply = msgs.some((m) => m.senderId === partnerId);
      if (hasPartnerReply) return;
      // Suggest via AI recovery flow; never auto-send.
      followupSuggestedTrackedRef.current = true;
      void trackAnalyticsEvent("first_message_followup_suggested", {
        plan_tier: aiTier,
        source: fromMatchRef.current ? "match_moment" : "chat_thread",
      });
      setAiOpen(true);
      setSuccessNudge({ message: t("chat.firstMessage.noReplyTryDifferent"), ttlMs: 10_000 });
    }, delayMs);
    return () => window.clearTimeout(handle);
  }, [aiTier, c.canCompose, c.messages, c.partnerUserId, t]);

  useEffect(() => {
    if (reviveTimerRef.current != null) {
      window.clearTimeout(reviveTimerRef.current);
      reviveTimerRef.current = null;
    }
    const partnerId = c.partnerUserId ?? null;
    const viewerId = c.viewer?.userId ?? null;
    if (!partnerId || !viewerId || !c.canCompose) return;

    const msgs = c.messages || [];
    const last = msgs.length ? msgs[msgs.length - 1] : null;
    if (!last || Number(last.senderId) !== Number(viewerId)) return;

    const msgId = String(last.id ?? "");
    if (!msgId) return;

    const ts = Date.parse(String(last.timestamp ?? last.createdAt ?? "").trim());
    if (!Number.isFinite(ts)) return;

    const isDev = typeof process !== "undefined" && process.env.NODE_ENV === "development";
    const minMs = isDev ? 20_000 : 10 * 60 * 1000;
    const maxMs = isDev ? 65_000 : 30 * 60 * 1000;
    const fireAt = ts + minMs + Math.floor(Math.random() * Math.max(1, maxMs - minMs));
    const delay = Math.max(0, fireAt - Date.now());

    reviveTimerRef.current = window.setTimeout(() => {
      reviveTimerRef.current = null;
      const cur = messagesLiveRef.current.length ? messagesLiveRef.current[messagesLiveRef.current.length - 1] : null;
      if (!cur || String(cur.id) !== msgId) return;
      if (Number(cur.senderId) !== Number(viewerId)) return;
      void trackAnalyticsEvent("chat_revive_nudge_shown", { partner_user_id: partnerId });
      const line = t("chat.nudge.quickPingDraft");
      if (!draftLiveRef.current.trim()) {
        c.setDraft(line);
      }
      setSuccessNudge({ message: t("retention.reopen.nudge"), ttlMs: 12_000 });
    }, delay);

    return () => {
      if (reviveTimerRef.current != null) {
        window.clearTimeout(reviveTimerRef.current);
        reviveTimerRef.current = null;
      }
    };
  }, [c.messages, c.partnerUserId, c.viewer?.userId, c.canCompose, c.setDraft, t]);

  useEffect(() => {
    // Stronger nudge 10–30 min after no reply (still one-sided).
    const sentAt = firstOutgoingAtRef.current;
    if (!sentAt) return;
    if (firstReplyReceivedTrackedRef.current) return;
    if (strongerNoReplyNudgeRef.current) return;
    if (!c.canCompose) return;

    const isDev = typeof process !== "undefined" && process.env.NODE_ENV === "development";
    const minMs = isDev ? 25_000 : 10 * 60 * 1000;
    const maxMs = isDev ? 75_000 : 30 * 60 * 1000;
    const delayMs = minMs + Math.floor(Math.random() * Math.max(1, maxMs - minMs));

    const handle = window.setTimeout(() => {
      if (firstReplyReceivedTrackedRef.current) return;
      const partnerId = c.partnerUserId ?? null;
      if (partnerId == null) return;
      const msgs = messagesLiveRef.current || [];
      const hasPartnerReply = msgs.some((m) => m.senderId === partnerId);
      if (hasPartnerReply) return;
      strongerNoReplyNudgeRef.current = true;
      void trackAnalyticsEvent("nudge_stronger_no_reply_shown", { partner_user_id: partnerId });
      if (!draftLiveRef.current.trim()) c.setDraft(t("chat.nudge.quickPingDraft"));
      setSuccessNudge({ message: t("retention.reopen.nudge"), ttlMs: 12_000 });
    }, delayMs);
    return () => window.clearTimeout(handle);
  }, [c.canCompose, c.partnerUserId, c.setDraft, t]);

  // Readiness scoring is disabled (manual-only) to protect Gemini quota.

  useEffect(() => {
    // Success heuristic 3: recovery suggestion leads to partner reply soon after.
    const usedAt = recoveryUsedAtRef.current;
    if (!usedAt) return;
    if (recoverySuccessFiredRef.current === usedAt) return;
    const partnerId = c.partnerUserId ?? null;
    if (partnerId == null) return;
    const last = (c.messages || []).slice(-1)[0];
    if (!last) return;
    if (last.senderId !== partnerId) return;
    const ts = Date.parse((last.timestamp ?? last.createdAt ?? "").trim());
    if (!Number.isFinite(ts)) return;
    if (ts < usedAt || ts - usedAt > 6 * 60 * 60 * 1000) return;
    recoverySuccessFiredRef.current = usedAt;
    void trackAnalyticsEvent("ai_assist_success_recovery_worked", {
      plan_tier: aiTier,
      thread_state: threadStateFromMessages(c.messages.length),
    });
    maybeShowSuccessNudge(t("chat.thread.success.replyHelped"), { allowPlusTieIn: true });
  }, [aiTier, c.messages, c.partnerUserId, maybeShowSuccessNudge]);

  useEffect(() => {
    // Success heuristic 4: escalation hint followed by continued exchange.
    const usedAt = escalationUsedAtRef.current;
    if (!usedAt) return;
    if (escalationSuccessFiredRef.current === usedAt) return;
    const partnerId = c.partnerUserId ?? null;
    if (partnerId == null) return;
    const since = (c.messages || []).filter((m) => {
      const ts = Date.parse((m.timestamp ?? m.createdAt ?? "").trim());
      return Number.isFinite(ts) && ts >= usedAt;
    });
    if (since.length < 2) return;
    const hasPartner = since.some((m) => m.senderId === partnerId);
    if (!hasPartner) return;
    escalationSuccessFiredRef.current = usedAt;
    void trackAnalyticsEvent("ai_assist_success_escalation_progressed", {
      plan_tier: aiTier,
      thread_state: threadStateFromMessages(c.messages.length),
    });
    maybeShowSuccessNudge(t("chat.thread.success.nextStepNatural"), { allowPlusTieIn: false });
  }, [aiTier, c.messages, c.partnerUserId, maybeShowSuccessNudge]);
  const [aiLastInserted, setAiLastInserted] = useState<ViralAiInsertion | null>(null);
  const aiLastInsertedLiveRef = useRef<typeof aiLastInserted>(null);
  aiLastInsertedLiveRef.current = aiLastInserted;
  const brainLastSentAtRef = useRef<number | null>(null);
  const brainLastMetaRef = useRef<{
    variant: ChatBrainVariantKey;
    was_recommended: boolean;
    brain_mode: string;
  } | null>(null);
  const escalationLastInsertedRef = useRef<{ kind: "voice" | "video" | "date"; text: string; insertedAt: number } | null>(null);

  const chatBrainPanelRef = useRef<ChatAiBrainPanelHandle | null>(null);
  const [openerQuickBarOpen, setOpenerQuickBarOpen] = useState(false);
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [viralShareOpen, setViralShareOpen] = useState(false);
  const [viralSharePrompt, setViralSharePrompt] = useState<{ partnerMsg: string; aiReply: string; resultText: string } | null>(null);
  const [viralToast, setViralToast] = useState<string | null>(null);
  const [composerFocusKey, setComposerFocusKey] = useState(0);
  const [composerDraftBurstKey, setComposerDraftBurstKey] = useState(0);
  const [composerSendPulse, setComposerSendPulse] = useState(false);
  const [reviewPromptOpen, setReviewPromptOpen] = useState(false);
  const reviewPromptTimerRef = useRef<number | null>(null);
  const scheduleSmartReviewRef = useRef<(opts: { trigger: SmartReviewTrigger; firstMessageJustSent?: boolean }) => void>(() => {});
  const [videoBusy, setVideoBusy] = useState(false);

  const scheduleReviewPromptCheck = useCallback((opts: { trigger: SmartReviewTrigger; firstMessageJustSent?: boolean }) => {
    if (isDemoChat) return;
    if (typeof window === "undefined") return;
    if (reviewPromptTimerRef.current != null) {
      window.clearTimeout(reviewPromptTimerRef.current);
      reviewPromptTimerRef.current = null;
    }
    reviewPromptTimerRef.current = window.setTimeout(() => {
      reviewPromptTimerRef.current = null;
      const inserts = getAiBrainInsertSessionCount();
      const fm = Boolean(opts.firstMessageJustSent);
      if (!shouldOfferSmartReviewPrompt({ trigger: opts.trigger, aiBrainInsertCount: inserts, firstMessageJustSent: fm })) return;
      markReviewPromptShownThisSession();
      markReviewPromptShownTimestamp();
      void trackAnalyticsEvent("review_prompt_shown", {
        trigger: opts.trigger,
        first_message_ai: fm,
        brain_inserts: inserts,
      });
      setReviewPromptOpen(true);
    }, 850);
  }, [isDemoChat]);

  scheduleSmartReviewRef.current = scheduleReviewPromptCheck;

  useEffect(() => {
    return () => {
      if (typeof window !== "undefined" && reviewPromptTimerRef.current != null) {
        window.clearTimeout(reviewPromptTimerRef.current);
        reviewPromptTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (c.loadError) markReviewSessionChatError();
  }, [c.loadError]);

  useEffect(() => {
    if (!(c.draft ?? "").trim()) setOpenerQuickBarOpen(false);
  }, [c.draft]);

  useEffect(() => {
    setOpenerQuickBarOpen(false);
    setShareModalOpen(false);
    setReviewPromptOpen(false);
    setViralShareOpen(false);
    setViralSharePrompt(null);
  }, [c.partnerUserId]);

  useEffect(() => {
    if (!viralToast) return;
    setSuccessNudge({ message: viralToast, ttlMs: 8000 });
    setViralToast(null);
  }, [viralToast]);

  useEffect(() => {
    const fromMatch = (searchParams?.get("match") ?? "") === "1";
    const wantOpeners = (searchParams?.get("ai") ?? "") === "openers";
    fromMatchRef.current = fromMatch;
    if (!fromMatch || !wantOpeners) return;
    // Wait until thread state is known; only auto-open for empty threads.
    if (!c.canCompose) return;
    if (c.messages.length !== 0) return;
    if ((c.draft ?? "").trim()) return;
    if (promptShownRef.current) return;
    promptShownRef.current = true;
    setAiOpen(true);
    void trackAnalyticsEvent("first_message_prompt_shown", {
      source: "match_moment",
      plan_tier: aiTier,
    });
  }, [aiTier, c.canCompose, c.draft, c.messages.length, searchParams]);

  useEffect(() => {
    const fromMatchUrl = (searchParams?.get("match") ?? "") === "1";
    if (!fromMatchUrl) return;
    if (!c.canCompose) return;
    if (c.messages.length !== 0) return;
    if (matchMomentBannerShownRef.current) return;
    if (aiTier === "free" && !softMonClaimOnce("match_moment")) return;
    matchMomentBannerShownRef.current = true;
    if (aiTier === "free") {
      setPaywallConversionHint("after_match");
      void trackAnalyticsEvent("conversion_after_match", {
        stage: "shown",
        surface: "match_moment_banner",
        plan_tier: aiTier,
        partner_user_id: c.partnerUserId ?? null,
      });
      void trackAnalyticsEvent("paywall_shown", {
        surface: "match_moment_banner",
        plan_tier: aiTier,
        partner_user_id: c.partnerUserId ?? null,
      });
      setSuccessNudge({
        message: t("chat.matchMoment.banner"),
        ctaHref: "#",
        ctaPreventNavigation: true,
        ctaLabel: t("chat.softMon.ctaContinue"),
        ttlMs: 16_000,
        appearance: "soft",
        onCtaClick: () => {
          setAiOpen(true);
          void trackAnalyticsEvent("conversion_after_match", {
            stage: "cta_click",
            surface: "match_moment_banner",
            plan_tier: aiTier,
            partner_user_id: c.partnerUserId ?? null,
          });
        },
      });
    } else {
      setSuccessNudge({
        message: t("chat.matchMoment.banner"),
        ttlMs: 12_000,
      });
    }
  }, [searchParams, c.canCompose, c.messages.length, aiTier, t, c.partnerUserId]);

  useEffect(() => {
    // Matches screen chips: prefill draft + open quick-send bar.
    if (!wantQuickSendBar) return;
    if (!prefillDraft) return;
    if (!c.canCompose) return;
    if (c.messages.length !== 0) return;
    if ((c.draft ?? "").trim()) return;
    // Allow the effect to prefill UI, but sending must be idempotent and happen at most once.
    c.setDraft(prefillDraft);
    setOpenerQuickBarOpen(true);
    setComposerFocusKey((k) => k + 1);
    setComposerDraftBurstKey((k) => k + 1);
    setComposerSendPulse(true);
    window.setTimeout(() => setComposerSendPulse(false), 1200);
  }, [c.canCompose, c.draft, c.messages.length, c.setDraft, prefillDraft, wantQuickSendBar]);

  useEffect(() => {
    // URL quick_send may execute ONLY ONCE. Guard with sessionStorage idempotency key.
    if (!wantQuickSendBar) return;
    if (!prefillDraft) return;
    if (!c.canCompose) return;
    if (c.messages.length !== 0) return;
    if (!c.partnerUserId) return;
    if (quickSendTriggeredRef.current) return;

    const draftNorm = prefillDraft.trim();
    if (!draftNorm) return;
    const key = `quick_send:${c.partnerUserId}:${hashDraftForKey(draftNorm)}`;
    quickSendTriggeredRef.current = true;

    let alreadyUsed = false;
    try {
      alreadyUsed = sessionStorage.getItem(key) === "1";
      if (!alreadyUsed) sessionStorage.setItem(key, "1");
    } catch {
      // If storage fails, still proceed once per mount.
    }

    // Prevent navigation/re-render loops: remove params immediately.
    cleanQuickSendUrl();

    if (alreadyUsed) return;

    // Fire the send once with explicit idempotency key.
    markUiSendingLocked(true);
    void c.actions
      .sendMessageNow(draftNorm, { idempotencyKey: key })
      .catch(() => {})
      .finally(() => markUiSendingLocked(false));
  }, [c.actions, c.canCompose, c.messages.length, c.partnerUserId, prefillDraft, wantQuickSendBar]);

  useEffect(() => {
    // Reset per-thread refs when switching threads.
    firstMessageSentTrackedRef.current = false;
    firstReplyReceivedTrackedRef.current = false;
    firstMessageAiAssistedTrackedRef.current = false;
    firstOutgoingAtRef.current = 0;
    followupSuggestedTrackedRef.current = false;
    promptShownRef.current = false;
    openerUsedAfterMatchRef.current = false;
    escalationLastInsertedRef.current = null;
    noFirstMessageNudgeRef.current = false;
    strongerNoReplyNudgeRef.current = false;
    if (reviveTimerRef.current != null) {
      window.clearTimeout(reviveTimerRef.current);
      reviveTimerRef.current = null;
    }
    prevThreadMsgCountRef.current = 0;
    setPartnerReplyGlowId(null);
    prevOutboundForMatchRef.current = -1;
    matchMomentBannerShownRef.current = false;
  }, [c.partnerUserId]);

  useEffect(() => {
    const meId = c.viewer?.userId != null ? Number(c.viewer.userId) : null;
    const pid = c.partnerUserId != null ? Number(c.partnerUserId) : null;
    if (meId == null || pid == null || meId <= 0 || pid <= 0) return;
    const out = (c.messages || []).filter((m) => Number(m.senderId) === meId && String((m as { content?: string }).content ?? "").trim().length > 0).length;
    if (prevOutboundForMatchRef.current < 0) {
      prevOutboundForMatchRef.current = out;
      return;
    }
    if (prevOutboundForMatchRef.current === 0 && out >= 1) {
      try {
        const raw = sessionStorage.getItem(`neyra_match_partner_ts:${pid}`);
        if (raw != null && raw !== "") {
          const t0 = Number(raw);
          if (Number.isFinite(t0)) {
            const seconds_since_match_modal = Math.max(0, (Date.now() - t0) / 1000);
            void trackAnalyticsEvent("match_to_message_rate", { partner_user_id: pid, seconds_since_match_modal });
            sessionStorage.removeItem(`neyra_match_partner_ts:${pid}`);
          }
        }
      } catch {
        /* ignore */
      }
    }
    prevOutboundForMatchRef.current = out;
  }, [c.messages, c.partnerUserId, c.viewer?.userId]);

  useEffect(() => {
    // Best-effort plan lookup to distinguish premium_plus from premium.
    // Do not block chat on this; default tier resolver will treat missing plan as premium if isPremium is true.
    if (!c.viewer?.isPremium) return;
    let cancelled = false;
    void apiFetch("/subscriptions/me", { metaReason: "chat-ai-plan" })
      .then((data) => {
        if (cancelled) return;
        const code = String((data && typeof data === "object" ? (data as any).plan_code || (data as any).plan : "") || "");
        setPlanCode(code);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [c.viewer?.isPremium]);

  useEffect(() => {
    void maybeEmitHookConverted(aiTier);
  }, [aiTier]);

  const coachMessages = useMemo(() => {
    const meId = c.viewer?.userId != null ? Number(c.viewer.userId) : null;
    const themId = c.partnerUserId != null ? Number(c.partnerUserId) : null;
    const rows = (c.messages || [])
      .slice(-30)
      .map((m: any) => {
        const sender = Number(m?.senderId);
        const role = meId != null && sender === meId ? ("me" as const) : themId != null && sender === themId ? ("them" as const) : null;
        const text = String(m?.content || "").trim();
        if (!role || !text) return null;
        return { role, text };
      })
      .filter(Boolean) as { role: "me" | "them"; text: string }[];
    return rows.slice(-24);
  }, [c.messages, c.partnerUserId, c.viewer?.userId]);

  const coachEnabled = !coachHidden && !c.blockedThread && c.partnerUserId != null;

  const showCoach =
    coachEnabled &&
    coachTip &&
    coachTip.state !== "idle" &&
    Boolean(coachTip.message.trim()) &&
    c.messages.length > 0;

  useEffect(() => {
    const next = computeHealthPack({
      messages: c.messages,
      viewerId: c.viewer?.userId ?? null,
      partnerId: c.partnerUserId ?? null,
      prevScore: healthScoreRef.current,
      t,
    });
    if (!next) {
      setHealth(null);
      healthScoreRef.current = 0.55;
      return;
    }
    healthScoreRef.current = next.score;
    setHealth((prev) => {
      // prevent wild state flips (small hysteresis)
      if (!prev) return next;
      if (prev.state === next.state) return next;
      const s = next.score;
      if (prev.state === "strong" && s > 0.64) return { ...next, state: "strong" };
      if (prev.state === "needs" && s < 0.50) return { ...next, state: "needs" };
      // otherwise, require clearer crossing to flip
      if (next.state === "strong" && s < 0.76) return { ...next, state: "building" };
      if (next.state === "needs" && s > 0.38) return { ...next, state: "building" };
      return next;
    });
  }, [c.messages, c.partnerUserId, c.viewer?.userId, t]);

  // Combine with coach: if 🔴 and no coach currently shown, gently trigger coach on cooldown.
  useEffect(() => {
    if (!health) return;
    if (health.state !== "needs") return;
    if (showCoach) return;
    void maybeFetchCoach("inactive");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [health?.state]);

  async function maybeFetchCoach(trigger: "typed" | "received" | "inactive") {
    if (!coachEnabled) return;
    if (coachInFlightRef.current) return;
    if (!c.canCompose) return;
    if (!c.partnerUserId || !c.viewer?.userId) return;
    if (!coachMessages.length) return;

    const now = Date.now();
    const minGapMs = 55_000;
    if (now - coachLastShownAtRef.current < minGapMs) return;

    const draft = String(c.draft ?? "").trim();
    // typed: only when user has a draft; received/inactive: draft should be empty to avoid noise.
    if (trigger === "typed" && !draft) return;
    if ((trigger === "received" || trigger === "inactive") && draft) return;

    // lightweight "not intrusive": only coach when there is enough context
    const msgCount = coachMessages.length;
    if (msgCount < 4 && trigger !== "typed") return;

    const incoming = (c.messages || []).slice(-1)[0] ?? null;
    const incomingId = incoming ? String((incoming as any).rawId ?? incoming.id ?? incoming.createdAt ?? "") : "";
    if (trigger === "received" && incomingId && incomingId === coachLastIncomingIdRef.current) return;

    coachInFlightRef.current = true;
    coachLastTriggerRef.current = trigger;
    if (trigger === "received" && incomingId) coachLastIncomingIdRef.current = incomingId;
    try {
      const readiness = await fetchReadinessScore({
        messages: coachMessages,
        draft: draft || null,
        planTier: aiTier,
      });
      const res = await fetchAiCoach({
        messages: coachMessages,
        draft: draft || null,
        readinessScore: readiness?.score ?? null,
      });
      if (!res) return;

      const state: CoachState =
        res.state === "opportunity" || res.state === "caution" || res.state === "nudge" ? (res.state as any) : "idle";
      const level: CoachLevel = state === "opportunity" ? "safe" : state === "caution" ? "risky" : "better";
      const msg = String(res.message || "").trim();
      const sig = `${state}:${level}:${msg}`;
      if (!msg || sig === coachLastSigRef.current) return;
      coachLastSigRef.current = sig;
      coachLastShownAtRef.current = Date.now();
      setCoachTip({ state, level, message: msg, actions: res.actions || [] });
      void trackAnalyticsEvent("ai_coach_tip_shown", { trigger, state, level });
    } catch {
      /* Background coach must never surface Next runtime overlay */
    } finally {
      coachInFlightRef.current = false;
    }
  }

  // Trigger: after user types (debounced pause).
  const typingTimerRef = useRef<number | null>(null);
  useEffect(() => {
    if (!coachEnabled) return;
    if (typingTimerRef.current != null && typeof window !== "undefined") window.clearTimeout(typingTimerRef.current);
    coachLastInteractionAtRef.current = Date.now();
    if (!String(c.draft ?? "").trim()) return;
    if (typeof window === "undefined") return;
    typingTimerRef.current = window.setTimeout(() => {
      typingTimerRef.current = null;
      void maybeFetchCoach("typed");
    }, 950);
    return () => {
      if (typingTimerRef.current != null && typeof window !== "undefined") {
        window.clearTimeout(typingTimerRef.current);
        typingTimerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [c.draft, coachEnabled]);

  // Trigger: after receiving a message.
  useEffect(() => {
    if (!coachEnabled) return;
    const last = (c.messages || []).slice(-1)[0] ?? null;
    if (!last) return;
    if (Number(last.senderId) !== Number(c.partnerUserId)) return;
    coachLastInteractionAtRef.current = Date.now();
    void maybeFetchCoach("received");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [c.messages.length, coachEnabled, c.partnerUserId]);

  // Trigger: inactivity (30–60s).
  useEffect(() => {
    if (!coachEnabled) return;
    if (typeof window === "undefined") return;
    if (coachInactivityTimerRef.current != null) window.clearTimeout(coachInactivityTimerRef.current);
    coachInactivityTimerRef.current = window.setTimeout(() => {
      coachInactivityTimerRef.current = null;
      const idleMs = Date.now() - coachLastInteractionAtRef.current;
      if (idleMs < 30_000) return;
      void maybeFetchCoach("inactive");
    }, 45_000);
    return () => {
      if (coachInactivityTimerRef.current != null && typeof window !== "undefined") {
        window.clearTimeout(coachInactivityTimerRef.current);
        coachInactivityTimerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [coachEnabled, c.messages.length, c.draft]);

  const lastMessageAgeMinutes = useMemo(() => {
    const last = (c.messages || []).filter((m) => (m.content ?? "").trim()).slice(-1)[0];
    if (!last) return null;
    const ts = (last.timestamp ?? last.createdAt ?? "").trim();
    if (!ts) return null;
    const ms = Date.parse(ts);
    if (!Number.isFinite(ms)) return null;
    const diff = Date.now() - ms;
    if (!Number.isFinite(diff) || diff < 0) return 0;
    return Math.max(0, Math.round(diff / 60000));
  }, [c.messages]);

  useEffect(() => {
    const pid = c.partnerUserId != null ? Number(c.partnerUserId) : null;
    if (!pid || pid <= 0) return;
    const ageMin = lastMessageAgeMinutes;
    if (ageMin === null) return;
    if (retentionReopenEmittedRef.current === pid) return;
    retentionReopenEmittedRef.current = pid;
    if (ageMin >= 24 * 60) {
      void trackAnalyticsEvent("retention_chat_reopen", {
        partner_user_id: pid,
        inactive_minutes: ageMin,
      });
    }
  }, [c.partnerUserId, lastMessageAgeMinutes]);

  useEffect(() => {
    if (!c.partnerUserId) return;
    const pid = Number(c.partnerUserId);
    const n = (c.messages || []).filter((m) => String((m as any).content ?? "").trim()).length;
    if (n < 3 || n > 5) return;
    try {
      const day = utcDayKey();
      const key = `neyra:retn:momentum:${pid}:${day}`;
      if (typeof window !== "undefined" && window.localStorage.getItem(key) === day) return;
      if (typeof window !== "undefined") window.localStorage.setItem(key, day);
    } catch {
      /* ignore */
    }
    if (retentionMomentumShownRef.current) return;
    retentionMomentumShownRef.current = true;
    void trackAnalyticsEvent("retention_signal_shown", { kind: "chat_momentum_band", partner_user_id: pid, message_count: n });
    setSuccessNudge({ message: t("retention.chat.momentum"), ttlMs: 7800 });
  }, [c.messages, c.partnerUserId, t]);

  useEffect(() => {
    if (!AI_DEBUG_ENABLED) return;
    console.log("AI STATE", {
      hasMessages: c.messages.length > 0,
      draft: c.draft,
    });
  }, [c.draft, c.messages.length]);

  useEffect(() => {
    if (!aiOpen) return;
    console.warn("ai panel mounted", { partnerUserId: c.partnerUserId ?? null });
  }, [aiOpen, c.partnerUserId]);

  // NOTE: Gemini quota is very limited (e.g. 5 RPM / 20 RPD).
  // Do NOT auto-call readiness/coach/recovery/escalation on chat open.
  // These are now only triggered by explicit user actions (UI buttons), to prevent quota exhaustion.

  useEffect(() => {
    // If the user edits away from the inserted suggestion, mark it as "edited" for later analytics.
    if (!aiLastInserted) return;
    const current = (c.draft ?? "").trim();
    const original = (aiLastInserted.text ?? "").trim();
    if (!original) return;
    if (!current) return;
    if (current === original) return;
    // Keep the metadata; analytics will read "edited" at send time.
  }, [c.draft, aiLastInserted]);

  useEffect(() => {
    const ai = aiLastInserted;
    if (!ai || ai.kind !== "chat_brain") return;
    const pid = c.partnerUserId != null ? Number(c.partnerUserId) : null;
    if (!pid) return;
    const day = utcDayKey();
    const key = `neyra:retn:after_ai:${pid}:${day}`;
    try {
      if (typeof window !== "undefined" && sessionStorage.getItem(key) === "1") return;
      if (typeof window !== "undefined") sessionStorage.setItem(key, "1");
    } catch {
      /* ignore */
    }
    void trackAnalyticsEvent("retention_signal_shown", {
      kind: "after_ai_suggestion",
      partner_user_id: pid,
      variant: ai.variant,
    });
    setSuccessNudge({ message: t("retention.ai.afterReply"), ttlMs: 6800 });
  }, [aiLastInserted, c.partnerUserId, t]);

  const reportPrompt = useMemo(() => {
    return () => {
      const categoryRaw =
        (typeof window !== "undefined"
          ? window.prompt(t("chat.thread.reportPrompt.category"), "")
          : "") || "harassment";
      const category = categoryRaw.trim().toLowerCase() as ReportCategory;
      const details =
        typeof window !== "undefined" ? window.prompt(t("chat.thread.reportPrompt.details"), "") || "" : "";
      void c.actions.reportPartner(category, details);
    };
  }, [c.actions, t]);

  const threadLoadErrorEmptyState =
    c.loadError && c.messages.length === 0 ? (
      <ChatEmptyState
        title={t("chat.thread.error.title")}
        description={loadErrorText}
        allowRawDescription={isRawI18nText(c.loadError)}
      >
        {typeof loadErrorText === "string" && loadErrorText.toLowerCase().includes("match before chatting") ? (
          <div style={{ display: "grid", gap: 10 }}>
            <Link href="/discover" className="btn btn-primary">
              {renderDebugText(t("chat.thread.matchRequired.likeToMatch"), { component: "ChatThreadPage", prop: "likeToMatchLink" })}
            </Link>
            <Link href="/matches" className="btn btn-ghost">
              {renderDebugText(t("chat.thread.viewMatches"), { component: "ChatThreadPage", prop: "viewMatchesLink" })}
            </Link>
          </div>
        ) : null}
        <Button type="button" variant="primary" onClick={() => void c.actions.refresh()}>
          {t("common.tryAgain")}
        </Button>
      </ChatEmptyState>
    ) : null;

  const showFirstMessageSuggestion = !c.showMessageSkeleton && !c.loadError && c.partnerUserId != null && c.messages.length === 0 && c.canCompose;
  const compactFirstChatTurn = c.messages.length === 0;

  const incomingVideoUrl = useMemo(() => {
    const pid = c.partnerUserId ?? null;
    if (!pid) return "";
    const last = (c.messages || []).slice(-1)[0] ?? null;
    if (!last) return "";
    // Only show banner for partner-initiated message containing a Daily room link.
    if (Number(last.senderId) !== Number(pid)) return "";
    const text = String((last as any).content || "").trim();
    const m = text.match(/https:\/\/[^\s]+daily\.co\/[a-zA-Z0-9_-]+/);
    return m ? String(m[0]) : "";
  }, [c.messages, c.partnerUserId]);

  const inlineReplySuggestionsUnderLastMessage = useMemo(() => {
    if (!c.messages.length) return null;
    const last = c.messages[c.messages.length - 1];
    if (Number(last.senderId) !== Number(c.partnerUserId)) return null;
    if (!String(last.content ?? "").trim()) return null;
    if (String(c.draft ?? "").trim()) return null;
    return (
      <ChatReplySuggestionsInline
        partnerUserId={c.partnerUserId}
        viewerUserId={c.viewer?.userId ?? null}
        messages={c.messages}
        composerDraft={c.draft ?? ""}
        aiTier={aiTier}
        disabled={!c.canCompose || c.sending || Boolean(c.blockedThread)}
        onInsert={(text, meta) => {
          void trackAnalyticsEvent("reply_suggestion_inserted", {
            partner_user_id: c.partnerUserId,
            style: meta.style,
            index: meta.index,
          });
          markReviewSessionRealAiUsed();
          setAiLastInserted({ kind: "timed_reply", text, style: meta.style, index: meta.index });
          c.setDraft(text);
          setOpenerQuickBarOpen(true);
          setComposerFocusKey((k) => k + 1);
          setComposerDraftBurstKey((k) => k + 1);
          setComposerSendPulse(true);
          window.setTimeout(() => setComposerSendPulse(false), 1200);
        }}
      />
    );
  }, [
    c.blockedThread,
    c.canCompose,
    c.draft,
    c.messages,
    c.partnerUserId,
    c.sending,
    c.setDraft,
    aiTier,
    c.viewer?.userId,
  ]);

  async function startVideoCall() {
    if (!c.partnerUserId) return;
    if (videoBusy) return;
    setVideoBusy(true);
    try {
      const res = (await apiFetch("/video/create-room", {
        method: "POST",
        metaReason: "video-create-room",
        skipThrottle: true,
        body: JSON.stringify({ partner_user_id: Number(c.partnerUserId) }),
      })) as { url?: string };
      const roomUrl = String(res?.url || "").trim();
      if (!roomUrl) throw new Error("roomUrl missing");

      // Send join link into chat (manual action by the user).
      const msg = t("chat.videoCall.startedMessage", { url: roomUrl });
      await c.actions.sendMessageNow(msg);

      const roomId = roomUrl.split("/").filter(Boolean).slice(-1)[0] || "";
      void trackAnalyticsEvent("video_call_started", { partner_user_id: c.partnerUserId, room_id: roomId });
      router.push(`/video/${encodeURIComponent(roomId)}?url=${encodeURIComponent(roomUrl)}`);
    } catch (e) {
      // Best-effort error toast via existing nudge mechanism.
      setSuccessNudge({ message: t("errors.api.video.daily_unavailable"), ttlMs: 8000 });
    } finally {
      setVideoBusy(false);
    }
  }

  // These endpoints used to auto-call on thread updates and quickly exhaust Gemini quota.
  // Until we reintroduce them as explicit, user-click actions, keep them fully disabled.
  const readinessVisible = false;
  const coachVisible = false;
  const recoveryVisible = false;
  const escalationVisible = false;
  const escalationTeaserVisible = false;
  const readinessHiddenReason = "Readiness disabled: manual-only to protect Gemini quota.";
  const coachHiddenReason = "Coach disabled: manual-only to protect Gemini quota.";
  const recoveryHiddenReason = "Recovery disabled: manual-only to protect Gemini quota.";
  const escalationHiddenReason = "Escalation disabled: manual-only to protect Gemini quota.";
  const forceVisibleReason = FORCE_AI_VISIBLE ? "FORCE_AI_VISIBLE active: chat AI surfaces are forced visible in dev." : null;

  useEffect(() => {
    logAiGate("chat-thread-ui", {
      forceVisible: FORCE_AI_VISIBLE,
      aiTier,
      aiPanelOpen,
      messageCount: c.messages.length,
      hasDraft: Boolean((c.draft ?? "").trim()),
      readinessVisible,
      coachVisible,
      recoveryVisible,
      escalationVisible,
      escalationTeaserVisible,
      readinessHiddenReason,
      coachHiddenReason,
      recoveryHiddenReason,
      escalationHiddenReason,
    });
  }, [
    aiPanelOpen,
    aiTier,
    c.draft,
    c.messages.length,
    coachHiddenReason,
    coachVisible,
    escalationHiddenReason,
    escalationTeaserVisible,
    escalationVisible,
    readinessHiddenReason,
    readinessVisible,
    recoveryHiddenReason,
    recoveryVisible,
  ]);

  async function handleComposerSend() {
    const now = Date.now();
    if (sendLockRef.current) return;
    if (now - lastSendAttemptAtRef.current < 800) return;
    lastSendAttemptAtRef.current = now;
    markUiSendingLocked(true);
    try {
      // Coach should not linger after an action.
      if (coachTip) setCoachTip(null);
      const draft = (c.draft ?? "").trim();
      const draftHash = draft ? `${draft.length}:${draft.slice(0, 64)}` : "";
      const ai = aiLastInsertedLiveRef.current ? { ...aiLastInsertedLiveRef.current } : null;
      const inserted = (ai?.text ?? "").trim();
      const edited = Boolean(ai && inserted && draft && draft !== inserted);
      const wasEmptyThread = c.messages.length === 0;
      let messageRewardCandidate = false;

    if (draft && c.partnerUserId && !c.sending) {
      const alreadyWarned = conversionWarnedHashRef.current === draftHash;
      if (!alreadyWarned) {
        try {
          const q = await apiFetch("/messages/quality", {
            method: "POST",
            metaReason: "message-quality",
            body: JSON.stringify({
              receiver_id: Number(c.partnerUserId),
              content: draft,
              conversation_context: conversationContext(c.messages),
            }),
            skipThrottle: true,
          });
          const mayNot = Boolean(q && typeof q === "object" ? (q as any).may_not_get_reply ?? (q as any).mayNotGetReply : false);
          if (mayNot) {
            conversionWarnedHashRef.current = draftHash;
            conversionUsedRewriteRef.current = false;
            void trackAnalyticsEvent("conversion_warning_shown", {
              partner_user_id: Number(c.partnerUserId),
              risk_score: Number((q as any)?.risk_score ?? (q as any)?.riskScore ?? 0) || 0,
              quality_flags: (q as any)?.quality_flags ?? (q as any)?.qualityFlags ?? [],
              plan_tier: aiTier,
            });

            if (aiTier === "free") {
              setSuccessNudge({
                message: t("chat.convert.mayNotReply"),
                ctaHref: "/subscription",
                ctaLabel: t("chat.convert.wantBetter"),
                ttlMs: 14_000,
              });
              return;
            }

            setSuccessNudge({ message: t("chat.convert.mayNotReply"), ttlMs: 12_000 });
            setAiOpen(true);
            return;
          }
          messageRewardCandidate = Boolean(q && typeof q === "object" && (q as any).feels_engaging);
        } catch {
          messageRewardCandidate = messageFeelsEngagingHeuristic(draft);
        }
      } else {
        messageRewardCandidate = messageFeelsEngagingHeuristic(draft);
      }
    }

    if (ai && inserted && edited && (ai.kind === "openers" || ai.kind === "rewrite")) {
      void trackAiAssistEditedAfterInsert({
        assist_type: ai.kind === "rewrite" ? "rewrite" : "opener",
        mode: ai.mode,
        thread_state: threadStateFromMessages(c.messages.length),
        draft_state: draftStateFromDraft(c.draft),
        source: "inline_panel",
        plan_tier: aiTier,
      });
    }
    if (ai?.kind === "chat_brain" && inserted && edited) {
      void (async () => {
        try {
          const { postAiMemoryEvent } = await import("../../../lib/chat/api");
          void postAiMemoryEvent({
            event_type: "cb_edit",
            partner_user_id: Number(c.partnerUserId ?? 0),
            metadata_json: { variant: ai.variant, source: "chat_brain" },
          }).catch(() => {});
        } catch {
          /* ignore */
        }
      })();
    }

      // Keep idempotency stable within the debounce window so double clicks/Enter spam dedupe server-side too.
      const bucket = Math.floor(now / 800);
      const idempotencyKey =
        c.partnerUserId && draft
          ? `send:${c.partnerUserId}:${hashDraftForKey(draft)}:${String(bucket)}`
          : `send:${String(bucket)}`;
      let assistMeta: MessageAssistMeta | undefined;
      if (ai?.kind === "chat_brain" && inserted && draft.trim() && (draft === inserted || edited)) {
        assistMeta = {
          kind: "suggestion",
          mode: String(ai.brain_mode ?? ""),
          source: "chat_brain",
          variant: ai.variant,
          brain_mode: String(ai.brain_mode ?? ""),
          was_recommended: Boolean(ai.was_recommended),
          conversation_stage: ai.conversation_stage ?? null,
          conversation_mode: ai.conversation_mode ?? null,
          edited_after_insert: edited,
        };
      }
      const result = await c.actions.send({ idempotencyKey, assistMeta: assistMeta ?? null });
      if (result && "ok" in result && result.ok) {
        setSendSuccessBurstKey((k) => k + 1);
        if (!wasEmptyThread && messageRewardCandidate) {
          setSuccessNudge({ message: t("chat.send.goodOne"), ttlMs: 2600 });
        } else if (!wasEmptyThread && ai?.kind === "chat_brain" && inserted && Math.random() < 0.34) {
          setSuccessNudge({ message: t("chat.retention.smartMove"), ttlMs: 2200 });
        }
      }
    if (result && "ok" in result && result.ok && ai && inserted) {
      if (ai.kind === "chat_brain") {
        void trackAnalyticsEvent("ai_suggestion_sent", {
          mode: ai.brain_mode,
          variant: ai.variant,
          edited: Boolean(inserted && draft && draft !== inserted),
          partner_user_id: c.partnerUserId,
          plan_tier: aiTier,
          language: getStoredLocale() || "en",
          was_recommended: Boolean(ai.was_recommended),
        });
        void (async () => {
          try {
            const { postAiMemoryEvent } = await import("../../../lib/chat/api");
            void postAiMemoryEvent({
              event_type: "cb_send",
              partner_user_id: Number(c.partnerUserId ?? 0),
              metadata_json: {
                variant: ai.variant,
                draft_length: draft.length,
                has_emoji: /[\u{1F300}-\u{1FAFF}]/u.test(draft),
                was_recommended: Boolean(ai.was_recommended),
              },
            }).catch(() => {});
          } catch {
            /* ignore */
          }
        })();
        brainLastSentAtRef.current = Date.now();
        brainLastMetaRef.current = {
          variant: ai.variant,
          was_recommended: Boolean(ai.was_recommended),
          brain_mode: String(ai.brain_mode),
        };
      } else if (ai.kind === "openers" || ai.kind === "rewrite") {
        brainLastSentAtRef.current = null;
        brainLastMetaRef.current = null;
        void trackAiAssistSentAfterUse({
          assist_type: ai.kind === "rewrite" ? "rewrite" : "opener",
          mode: ai.mode,
          thread_state: threadStateFromMessages(c.messages.length),
          draft_state: draftStateFromDraft(c.draft),
          source: "inline_panel",
          plan_tier: aiTier,
        });
      } else {
        brainLastSentAtRef.current = null;
        brainLastMetaRef.current = null;
      }
      if (isStrongAiForViral(ai) && canOfferViralSharePrompt()) {
        incrementViralSharePromptSessionCount();
        setViralSharePrompt({
          partnerMsg: lastPartnerMessageFromThread(c.messages, c.partnerUserId),
          aiReply: inserted,
          resultText: draft,
        });
        void trackAnalyticsEvent("viral_share_prompt_shown", {
          partner_user_id: c.partnerUserId ?? null,
          ai_kind: ai.kind,
        });
      }
      aiAssistSentAtRef.current = Date.now();
      setAiLastInserted(null);
      setOpenerQuickBarOpen(false);
    }
    if (result && "ok" in result && result.ok && wasEmptyThread && !firstMessageSentTrackedRef.current) {
      firstMessageSentTrackedRef.current = true;
      firstOutgoingAtRef.current = Date.now();
      void trackAnalyticsEvent("first_message_sent", {
        plan_tier: aiTier,
        source: fromMatchRef.current ? "match_moment" : "chat_thread",
      });
      const ov = abCopyRef.current["chat.opener.nudge"]?.variant_id ?? "";
      if (ov) {
        trackAbMetric("message_sent", "chat.opener.nudge", ov);
      }
      setSuccessNudge({ message: t("chat.firstMessage.sentNudge") });
      scheduleReviewPromptCheck({ trigger: "first_message_ai", firstMessageJustSent: true });
    }
    if (result && "ok" in result && result.ok && wasEmptyThread && ai && inserted && !firstMessageAiAssistedTrackedRef.current) {
      firstMessageAiAssistedTrackedRef.current = true;
      void trackAnalyticsEvent("first_message_ai_assisted", {
        plan_tier: aiTier,
        source: fromMatchRef.current ? "match_moment" : "chat_thread",
      });
    }
    if (result && "ok" in result && result.ok && aiTier === "free") {
      const usedAi = Boolean(ai && inserted);
      if (usedAi) scheduleAiAssistPaywall();
    }
    if (result && "ok" in result && result.ok && !wasEmptyThread) {
      setSendMicroFeedbackKey((k) => k + 1);
    }
    } finally {
      markUiSendingLocked(false);
    }
  }

  if (c.partnerUserId == null) {
    return (
      <PageShell className="chat-page-shell">
        <section className="chat-module">
          <ChatEmptyState
            title={t("chat.thread.invalid.title")}
            description={t("chat.thread.invalid.description")}
          >
            <Link href="/chat" className="btn btn-primary">
              {renderDebugText(t("chat.thread.backInbox"), { component: "ChatThreadPage", prop: "backInboxLink" })}
            </Link>
            <Link href="/matches" className="btn btn-ghost">
              {renderDebugText(t("chat.thread.viewMatches"), { component: "ChatThreadPage", prop: "viewMatchesLink" })}
            </Link>
          </ChatEmptyState>
        </section>
      </PageShell>
    );
  }

  return (
    <PageShell className="chat-page-shell">
      <div className="chat-toolbar" aria-label={toolbarAria.text}>
        <div className="chat-toolbar__group">
          <Link href="/chat" className="chat-toolbar__link">
            {renderDebugText(t("chat.thread.allConversations"), { component: "ChatThreadPage", prop: "allConversationsLink" })}
          </Link>
          <Link href="/matches" className="chat-toolbar__link">
            {renderDebugText(t("navigation.matches"), { component: "ChatThreadPage", prop: "matchesLink" })}
          </Link>
        </div>

        <div className="chat-toolbar__group">
          <button
            type="button"
            className="chat-toolbar__button"
            onClick={() => void c.actions.refresh()}
            disabled={c.loading || c.refreshing}
          >
            {renderDebugText(c.refreshing ? t("common.refreshing") : t("chat.common.refresh"), {
              component: "ChatThreadPage",
              prop: "refreshButton",
            })}
          </button>
        </div>
      </div>

      <section data-testid="chat-thread" className="chat-module chat-thread-module">
        <div className="chat-thread-topbar">
          <ChatHeader
            partnerUserId={c.partnerUserId}
            partner={c.partner}
            seed={c.threadSeed}
            showSkeleton={c.showHeaderSkeleton}
            planTier={aiTier}
            partnerLastActiveAt={c.partnerLastActiveAt}
          />
          <div className="chat-thread-topbar__actions">
            <ChatThreadOverflowMenu
              disabled={c.loading || c.refreshing || Boolean(c.loadError)}
              partnerIgnored={Boolean(c.partner?.ignoredByMe)}
              canDelete={c.matchId != null}
              onDelete={() => void c.actions.deleteChat()}
              onIgnore={() => void c.actions.ignorePartner()}
              onUnignore={() => void c.actions.unignorePartner()}
            />
            {c.partnerUserId != null && !isDemoChat ? (
              <button
                type="button"
                className="chat-thread-topbar__action"
                onClick={() => void startVideoCall()}
                disabled={videoBusy || c.loading || c.refreshing || Boolean(c.loadError) || Boolean(c.blockedThread)}
              >
                {t("chat.videoCall.button")}
              </button>
            ) : null}
            {!isDemoChat ? (
              <>
                <button type="button" className="chat-thread-topbar__action" onClick={reportPrompt}>
                  {renderDebugText(t("common.report"), { component: "ChatThreadPage", prop: "reportButton" })}
                </button>
                <button
                  type="button"
                  className="chat-thread-topbar__action chat-thread-topbar__action--danger"
                  onClick={() => void c.actions.blockPartner()}
                  disabled={c.blocking}
                >
                  {renderDebugText(c.blocking ? t("common.blocking") : t("common.block"), {
                    component: "ChatThreadPage",
                    prop: "blockButton",
                  })}
                </button>
              </>
            ) : null}
          </div>
        </div>

        {(trialBanner || incomingVideoUrl) ? (
          <div className="chat-thread-lead">
            {trialBanner ? (
              <div
                style={{
                  marginTop: 10,
                  marginBottom: 10,
                  padding: "10px 12px",
                  borderRadius: 14,
                  border: "1px solid rgba(180, 120, 255, 0.28)",
                  background: "rgba(124, 92, 255, 0.10)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 12,
                }}
              >
                <div style={{ display: "grid", gap: 2 }}>
                  <div style={{ fontWeight: 850 }}>{trialBanner.text}</div>
                  {trialBanner.sub ? <div className="caption" style={{ opacity: 0.85 }}>{trialBanner.sub}</div> : null}
                </div>
                {trialBanner.kind === "expired" ? (
                  <Link
                    href="/subscription"
                    className="btn btn-primary"
                    style={{ whiteSpace: "nowrap" }}
                    onClick={() =>
                      void trackAnalyticsEvent("paywall_cta_clicked", {
                        cta_label: "continue",
                        surface: "chat_trial_expired_banner",
                      })
                    }
                  >
                    {t("common.continue")}
                  </Link>
                ) : null}
              </div>
            ) : null}

            {incomingVideoUrl ? (
              <div
                className="surface surface--inset"
                style={{
                  marginTop: 10,
                  marginBottom: 10,
                  padding: "10px 12px",
                  borderRadius: 14,
                  border: "1px solid rgba(255, 255, 255, 0.10)",
                  background: "rgba(255, 255, 255, 0.04)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 12,
                }}
              >
                <div style={{ display: "grid", gap: 2 }}>
                  <div style={{ fontWeight: 900 }}>{t("chat.videoCall.incomingTitle")}</div>
                  <div className="caption" style={{ opacity: 0.85 }}>
                    {incomingVideoUrl}
                  </div>
                </div>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => {
                    const roomId = incomingVideoUrl.split("/").filter(Boolean).slice(-1)[0] || "";
                    router.push(`/video/${encodeURIComponent(roomId)}?url=${encodeURIComponent(incomingVideoUrl)}`);
                  }}
                >
                  {t("chat.videoCall.join")}
                </button>
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="chat-thread-messages-slot">
          <RuntimeErrorBoundary label="chat-thread" fallback={<div className="chat-thread-body" />}>
            <ChatMessageList
            key={c.partnerUserId}
            showLoadingSkeleton={c.showMessageSkeleton}
            showPartnerTyping={c.partnerTyping}
            partnerTypingAriaLabel={
              isDemoChat ? t("chat.list.partnerTyping", { name: t("demo.profile.disclaimer_short") }) : undefined
            }
            messages={c.messages}
            reactionPendingByMessageId={c.reactionPendingByMessageId}
            currentUserId={c.viewer?.userId ?? null}
            partnerUserId={c.partnerUserId}
            partnerName={c.displayNameForThread || t("chat.thread.matchFallback")}
            partnerAvatarUrl={c.partnerAvatarUrl}
            myName={c.myName}
            myAvatarUrl={c.myAvatarUrl}
            emptyState={threadLoadErrorEmptyState}
            onRetryMessage={(tempId) => void c.actions.retrySend(tempId)}
            onRetryVoiceMessage={(tempId) => void c.actions.retryVoice(tempId)}
            onReplyMessage={(message) => c.setReplyTo(message)}
            onReactMessage={(id, emoji) => void c.actions.react(id, emoji)}
            inlineUnderLastPartnerMessage={inlineReplySuggestionsUnderLastMessage}
            hasMoreOlder={c.threadHasMore}
            olderLoading={c.olderLoading}
            onLoadOlder={() => void c.actions.loadOlderMessages()}
            partnerReplyGlowId={partnerReplyGlowId}
          />
          </RuntimeErrorBoundary>
        </div>

        {c.openerDrafting ? (
          <div className="chat-thread-opener-status caption" style={{ padding: "8px 18px", opacity: 0.85 }}>
            {t("chat.thread.openerDrafting")}
          </div>
        ) : null}

        <RuntimeErrorBoundary label="chat-ai-helpers" fallback={null}>
        <div className="chat-thread-ai-helpers">
        {showFirstMessageSuggestion && c.partnerUserId != null ? (
          <div style={{ padding: "14px 18px 0" }}>
            <ChatFirstMessageSuggestion
              partnerUserId={c.partnerUserId}
              matchContext={
                {
                  matchName: c.displayNameForThread || t("chat.thread.matchFallback"),
                  city: (c.partner as any)?.city ?? null,
                  bio: (c.partner as any)?.bio ?? (c.partner as any)?.about ?? null,
                  interests: (c.partner as any)?.interests ?? null,
                  tags: (c.partner as any)?.tags ?? null,
                } as AiOpenerMatchContext
              }
              aiCtx={aiCtx}
              disabled={c.sending || Boolean(c.blockedThread)}
              onInsert={(text, meta) => {
                void trackAnalyticsEvent("first_message_suggestion_inserted", {
                  partner_user_id: c.partnerUserId,
                  variant: meta.variant,
                  was_recommended: meta.wasRecommended,
                });
                markReviewSessionRealAiUsed();
                setAiLastInserted({
                  kind: "first_message",
                  text,
                  variant: meta.variant,
                  wasRecommended: meta.wasRecommended,
                });
                c.setDraft(text);
                setOpenerQuickBarOpen(true);
                setComposerFocusKey((k) => k + 1);
                setComposerDraftBurstKey((k) => k + 1);
                setComposerSendPulse(true);
                window.setTimeout(() => setComposerSendPulse(false), 1200);
              }}
              onOtherOptions={() => setAiOpen(true)}
            />
          </div>
        ) : null}

        {!compactFirstChatTurn ? (
          <>
            <ChatNextStepInline
              partnerUserId={c.partnerUserId}
              viewerUserId={c.viewer?.userId ?? null}
              messages={c.messages}
              disabled={!c.canCompose || c.sending || Boolean(c.blockedThread)}
              onSendText={async (text) => {
                const res = await c.actions.sendMessageNow(text);
                if (res && "ok" in res && res.ok) setSendMicroFeedbackKey((k) => k + 1);
                return res && "ok" in res && res.ok ? { ok: true } : { ok: false };
              }}
              onOpenOtherOptions={() => setAiOpen(true)}
            />

            <div style={{ padding: "0 18px", display: "grid", gap: 12 }}>
              <ChatMomentumDateCoach
                messages={c.messages}
                viewerUserId={c.viewer?.userId ?? null}
                partnerUserId={c.partnerUserId}
                composerDraft={c.draft ?? ""}
                aiTier={aiTier}
                disabled={!c.canCompose || c.sending || Boolean(c.blockedThread) || !c.partnerUserId}
                onOpenAi={() => setAiOpen(true)}
              />
              <ChatMeetingSuggestInline
                partnerUserId={c.partnerUserId}
                viewerUserId={c.viewer?.userId ?? null}
                userCity={String((c as any).myCity || "").trim() || null}
                messages={c.messages}
                conversationState={conversationState}
                composerDraft={c.draft ?? ""}
                disabled={!c.canCompose || c.sending || Boolean(c.blockedThread)}
                onInsert={(text, meta) => {
                  void trackAnalyticsEvent("meeting_message_sent", {
                    partner_user_id: c.partnerUserId,
                    kind: meta.kind,
                  });
                  markReviewSessionRealAiUsed();
                  setAiLastInserted({ kind: "meeting", text, meetingKind: meta.kind });
                  c.setDraft(text);
                  setOpenerQuickBarOpen(true);
                  setComposerFocusKey((k) => k + 1);
                  setComposerDraftBurstKey((k) => k + 1);
                  setComposerSendPulse(true);
                  window.setTimeout(() => setComposerSendPulse(false), 1200);
                }}
              />
              <ChatReviveSuggestionsInline
                partnerUserId={c.partnerUserId}
                viewerUserId={c.viewer?.userId ?? null}
                messages={c.messages}
                composerDraft={c.draft ?? ""}
                aiCtx={aiCtx}
                aiTier={aiTier}
                disabled={!c.canCompose || c.sending || Boolean(c.blockedThread)}
                onInsert={(text, meta) => {
                  void trackAnalyticsEvent("revive_suggestion_inserted", {
                    partner_user_id: c.partnerUserId,
                    style: meta.style,
                    index: meta.index,
                  });
                  markReviewSessionRealAiUsed();
                  setAiLastInserted({ kind: "revive", text, style: meta.style, index: meta.index });
                  c.setDraft(text);
                  setOpenerQuickBarOpen(true);
                  setComposerFocusKey((k) => k + 1);
                  setComposerDraftBurstKey((k) => k + 1);
                  setComposerSendPulse(true);
                  window.setTimeout(() => setComposerSendPulse(false), 1200);
                }}
              />
            </div>
          </>
        ) : null}
        </div>
        </RuntimeErrorBoundary>

        <div className="chat-thread-tail">
          {goodConversation ? (
            <div style={{ padding: "0 18px", marginTop: 10, display: "grid", gap: 8 }}>
              <Chip>🔥 {t("chat.thread.goodConversation")}</Chip>
              {aiTier === "free" ? (
                <div className="caption" style={{ opacity: 0.78, lineHeight: 1.4, maxWidth: "48ch" }}>
                  {t("chat.thread.momentumHint")}{" "}
                  <Link
                    className="chat-ai-inline__upgrade"
                    href="/premium?source=chat_momentum_hint"
                    onClick={() =>
                      void trackAnalyticsEvent("paywall_clicked", { source: "momentum", surface: "chat_momentum_hint" })
                    }
                  >
                    {t("chat.ai.limit.ctaUpgrade")}
                  </Link>
                </div>
              ) : null}
            </div>
          ) : null}

          {aiOpen && c.partnerUserId != null ? (
            <RuntimeErrorBoundary label="ai-suggestion-panel" fallback={null}>
              <ChatAiBrainPanel
              ref={chatBrainPanelRef}
              key={c.partnerUserId ?? 0}
              partnerUserId={c.partnerUserId ?? null}
              viewerUserId={c.viewer?.userId ?? null}
              messages={c.messages}
              disabled={!c.canCompose || Boolean(c.blockedThread)}
              composerAiOpen={aiOpen}
              threadIsEmpty={c.messages.length === 0}
              blockedTexts={(c.messages || []).map((m) => String((m as any)?.content || "").trim()).filter(Boolean)}
              aiCtx={aiCtx}
              aiTier={aiTier}
              freeAiChatSuggestionsLeft={freeAiChatSuggestionsLeft}
              onFreeAiChatConsumed={() => setAiChatUsageEpoch((n) => n + 1)}
              onInsertComposer={(text, meta) => {
                markReviewSessionRealAiUsed();
                setAiLastInserted({
                  kind: "chat_brain",
                  text,
                  brain_mode: meta.brain_mode as ChatBrainMode,
                  variant: meta.variant,
                  was_recommended: meta.was_recommended,
                  conversation_stage: meta.conversation_stage ?? null,
                  conversation_mode: meta.conversation_mode ?? null,
                });
                c.setDraft(text);
                trackDemoAiSuggestionUsed("chat_brain");
                if (c.messages.length === 0) bumpAiBrainInsertSessionCount();
                scheduleReviewPromptCheck({ trigger: "brain_insert", firstMessageJustSent: false });
                setOpenerQuickBarOpen(true);
                setComposerFocusKey((k) => k + 1);
                setComposerDraftBurstKey((k) => k + 1);
                setComposerSendPulse(true);
                window.setTimeout(() => setComposerSendPulse(false), 1200);
              }}
            />
            </RuntimeErrorBoundary>
          ) : null}

        {showCoach ? (
          <ChatCoachBar
            state={coachTip.state}
            level={coachTip.level}
            message={coachTip.message}
            actions={(coachTip.actions as any) || []}
            disabled={!c.canCompose}
            onViewed={() => void trackAnalyticsEvent("ai_coach_tip_viewed", { state: coachTip.state, level: coachTip.level, trigger: coachLastTriggerRef.current || "" })}
            onDismiss={() => {
              setCoachTip(null);
              void trackAnalyticsEvent("ai_coach_tip_dismissed", { state: coachTip.state, level: coachTip.level });
            }}
            onHide={() => {
              setCoachTip(null);
              setCoachHidden(true);
              try {
                localStorage.setItem(COACH_HIDDEN_KEY, "1");
              } catch {
                // ignore
              }
              void trackAnalyticsEvent("ai_coach_hidden", {});
            }}
            onAction={(action) => {
              setCoachTip(null);
              void trackAnalyticsEvent("ai_coach_action_clicked", { action_type: action.type });
              // Keep it non-intrusive: actions are suggestions; actual actions are handled elsewhere.
              if (action.type === "date_step") setAiOpen(true);
            }}
          />
        ) : null}

        {health ? (
          <div
            style={{
              marginTop: showCoach ? 10 : 0,
              padding: "10px 12px",
              borderRadius: 16,
              border:
                health.state === "strong"
                  ? "1px solid rgba(46, 204, 113, 0.35)"
                  : health.state === "needs"
                    ? "1px solid rgba(255, 138, 91, 0.35)"
                    : "1px solid rgba(255, 216, 87, 0.30)",
              background:
                health.state === "strong"
                  ? "rgba(46, 204, 113, 0.08)"
                  : health.state === "needs"
                    ? "rgba(255, 138, 91, 0.08)"
                    : "rgba(255, 216, 87, 0.07)",
              display: "grid",
              gap: 8,
            }}
            aria-label={t("chat.health.aria")}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
              <div style={{ fontWeight: 900 }}>
                {health.state === "strong"
                  ? `🟢 ${t("chat.health.state.strong")}`
                  : health.state === "needs"
                    ? `🔴 ${t("chat.health.state.needs")}`
                    : `🟡 ${t("chat.health.state.building")}`}
              </div>
              <div className="caption" style={{ opacity: 0.9 }}>
                {health.feedback}
              </div>
            </div>

            <div className="caption" style={{ opacity: 0.95 }}>
              <div style={{ fontWeight: 850 }}>{t("chat.health.whyTitle")}</div>
              <ul style={{ margin: "6px 0 0", paddingLeft: "1.25rem" }}>
                {health.why.slice(0, 3).map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>

            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
              <div className="caption" style={{ opacity: 0.95 }}>
                <span style={{ fontWeight: 850 }}>{t("chat.health.tryTitle")} </span>
                {health.tryTip}
              </div>
              {health.state === "strong" ? (
                <button type="button" className="btn btn-ghost" onClick={() => setAiOpen(true)} disabled={!c.canCompose}>
                  {t("chat.health.nextStepCta")}
                </button>
              ) : null}
            </div>
          </div>
        ) : null}

        {successNudge ? (
          <ChatAiSuccessNudge
            message={successNudge.message}
            ctaHref={successNudge.ctaHref ?? null}
            ctaLabel={successNudge.ctaLabel ?? null}
            ctaPreventNavigation={Boolean(successNudge.ctaPreventNavigation)}
            onCtaClick={successNudge.onCtaClick ?? null}
            ttlMs={successNudge.ttlMs}
            appearance={successNudge.appearance ?? "default"}
            onAutoDismiss={() => setSuccessNudge(null)}
          />
        ) : null}

        {viralInviteVisible ? (
          <ViralInviteNudge
            onInvite={() => {
              setViralInviteVisible(false);
              void trackAnalyticsEvent("viral_invite_nudge_cta", { source: "chat_after_reply" });
              router.push("/invite?source=chat_after_reply");
            }}
            onDismiss={() => setViralInviteVisible(false)}
          />
        ) : null}

        {AI_DEBUG_ENABLED ? (
          <div style={{ display: "grid", gap: 8, marginTop: successNudge ? 10 : 0 }}>
            <AiDebugPill label={forceVisibleReason} />
            <AiDebugPill label={readinessHiddenReason} />
            <AiDebugPill label={coachHiddenReason} />
            <AiDebugPill label={recoveryHiddenReason} />
            <AiDebugPill label={escalationHiddenReason} />
          </div>
        ) : null}

        {null}

        {null}

        {null}

          {viralSharePrompt && !viralShareOpen ? (
            <ViralShareInlineBar
              onShare={() => {
                trackViralShareClicked("chat_after_ai_send");
                setViralShareOpen(true);
              }}
              onDismiss={() => setViralSharePrompt(null)}
            />
          ) : null}
        </div>

        <div className="chat-composer-stack">
          {sendMicroFeedbackKey > 0 ? (
            <ChatSendMicroFeedback key={sendMicroFeedbackKey} onDone={dismissSendMicroFeedback} />
          ) : null}
          <div style={{ marginBottom: 10 }}>
            <ChatAiBar
              partnerUserId={c.partnerUserId}
              viewerUserId={c.viewer?.userId ?? null}
              messages={c.messages}
              draft={c.draft}
              disabled={!c.canCompose || Boolean(c.blockedThread)}
              aiCtx={{ uiLocale: uiLocaleTag }}
              aiTier={aiTier}
              onInsertDraft={(text) => {
                c.setDraft(text);
                setComposerFocusKey((k) => k + 1);
                setComposerDraftBurstKey((k) => k + 1);
              }}
            />
          </div>
          {openerQuickBarOpen ? (
            <ChatOpenerQuickBar
              disabled={!c.canCompose || Boolean(c.blockedThread)}
              onSend={() => void handleComposerSend()}
              onEdit={() => setComposerFocusKey((k) => k + 1)}
              onShare={() => setShareModalOpen(true)}
              onTryAnother={() => {
                chatBrainPanelRef.current?.regenerateAll();
                c.setDraft("");
                setOpenerQuickBarOpen(false);
              }}
            />
          ) : null}
          <ChatComposer
            value={c.draft}
            sending={c.sending || sendUiLocked}
            isSendingVoice={c.isSendingVoice}
            voiceSendPhase={c.voiceSendPhase}
            voiceSendError={c.voiceSendError}
            disabled={!c.canCompose}
            error={c.blockedThread ? t("chat.thread.blocked") : sendErrorText}
            autoFocus={autoFocusComposer}
            focusComposerKey={composerFocusKey}
            draftBurstKey={composerDraftBurstKey}
            sendSuccessKey={sendSuccessBurstKey}
            pulseSend={composerSendPulse}
            replyTo={
              c.replyTo
                ? {
                    label: t("chat.thread.replyTo", {
                      content: `${c.replyTo.content.slice(0, 80)}${c.replyTo.content.length > 80 ? "..." : ""}`,
                    }),
                  }
                : null
            }
            onCancelReply={() => c.setReplyTo(null)}
            onChange={c.setDraft}
            onSend={() => void handleComposerSend()}
            onSendVoice={(draft, caption) => c.actions.sendVoice(draft, caption)}
            aiActive={aiPanelOpen}
            onToggleAi={() => {
              setAiOpen((v) => {
                const next = !v;
                const assistType = (c.draft ?? "").trim() ? "rewrite" : "opener";
                const mode: AiAssistMode =
                  assistType === "rewrite"
                    ? "polish"
                    : // opener defaults to suggest_opener when opened via button
                      "suggest_opener";
                const payload = {
                  assist_type: assistType as "opener" | "rewrite",
                  mode,
                  thread_state: threadStateFromMessages(c.messages.length),
                  draft_state: draftStateFromDraft(c.draft),
                  source: "composer_button" as const,
                  plan_tier: aiTier,
                };
                if (next) void trackAiAssistRequested(payload);
                else void trackAiAssistDismissed(payload);
                return next;
              });
            }}
          />
          <div style={{ height: 180 }} aria-hidden />
        </div>
        <ViralShareModal open={shareModalOpen} onClose={() => setShareModalOpen(false)} />
        <ViralMomentShareModal
          open={viralShareOpen}
          aiText={viralSharePrompt?.aiReply ?? ""}
          partnerMessage={viralSharePrompt?.partnerMsg ?? ""}
          resultText={viralSharePrompt?.resultText ?? ""}
          onClose={() => {
            setViralShareOpen(false);
            setViralSharePrompt(null);
          }}
          onRewarded={(days) => setViralToast(`🎉 +${days} days unlocked`)}
        />
        <ReviewPromptSheet open={reviewPromptOpen} onClose={() => setReviewPromptOpen(false)} />
      </section>
    </PageShell>
  );
}
