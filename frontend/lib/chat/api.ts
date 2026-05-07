import {
  ApiThrottleSkipError,
  apiFetch,
  apiUpload,
  getToken,
  resolveMediaUrl,
  invalidateApiGetCache,
  isRequestAborted,
} from "../api";
import { postMatchesMarkSeen } from "../matchesMarkSeen";
import { dismissMatchesNewBadgeForPartner } from "../matchesNewBadge";
import { getNavBadgesSnapshot, optimisticOpenThreadNavBadges } from "../navBadgesStore";
import { debugChat } from "./debug";
import {
  normalizeChatViewer,
  normalizeConversationsPayload,
  normalizePartnerProfile,
  normalizeSendMessageResponse,
  normalizeThreadFetch,
} from "./normalize";
import type { ChatConversation, ChatMessage, ChatPartnerProfile, ChatSendResult, ChatViewer } from "./types";
import { logAiData, logAiGate } from "../aiDebug";
import { getAiLocalePayload, getCurrentUiLocale, getStoredLocale, getUiLocaleForAiRequests } from "../i18n";
import { detectMixedScripts, isTextLikelyInExpectedLanguage, resolveChatLanguage, resolveTone, type ChatTone, type ConversationState } from "./aiLanguageTone";
import { neyraAiLocaleDevLog, neyraAiLocaleRequestingSuggestions } from "./neyraAiLocaleLog";
import { trackAnalyticsEvent } from "../analytics";
import {
  chatBrainSuggestionsInflight,
  chatBrainSuggestionsMemo,
  clearOpenerSessionMemoryCache,
  openerSessionMem,
} from "./aiDedupeStores";

/** One in-flight sync per partner — avoids duplicate mark-seen / cache churn racing the thread load. */
const syncUnreadInFlight = new Map<number, Promise<void>>();

/** Coalesce concurrent GET /messages/:partnerId (poll + websocket + strict-mode double mount). */
const threadMessagesInflight = new Map<
  number,
  Promise<{
    messages: ChatMessage[];
    matchId: number | null;
    partnerLastReadAt: string | null;
    partnerLastActiveAt: string | null;
    threadHasMore: boolean;
  }>
>();

const THREAD_FETCH_DEBUG =
  typeof process !== "undefined" &&
  (process.env.NODE_ENV === "development" || process.env.NEXT_PUBLIC_DEBUG_API === "1");
const threadFetchCountsByPartner = new Map<number, number>();

/** Dev / NEXT_PUBLIC_DEBUG_API: completed GET /messages/:id count per partner (deduped calls still increment once per completed fetch). */
export function peekThreadFetchDebugCount(partnerUserId: number): number {
  return threadFetchCountsByPartner.get(Math.trunc(Number(partnerUserId))) ?? 0;
}

export const CHAT_INBOX_POLL_MS = 18_000;
export const CHAT_THREAD_POLL_MS = 18_000;
export const CHAT_SYNC_EVENT = "neyra:chat-sync";
export const VIEWER_REFRESH_EVENT = "neyra:viewer-refresh";

export type ChatSyncDetail =
  | {
      type: "threadOpened" | "messageSent" | "messageReceived" | "inboxInvalidate";
      partnerUserId: number;
    }
  | { type: "wsReconnected"; partnerUserId?: number };

export type AiLanguageToneContext = {
  viewer?: Pick<ChatViewer, "nativeLanguage" | "additionalLanguages"> | null;
  partner?: Pick<ChatPartnerProfile, "nativeLanguage" | "additionalLanguages"> | null;
  uiLocale?: string | null;
  conversationState?: ConversationState;
  isFirstMessage?: boolean;
  overrideLanguage?: string | null;
  overrideTone?: ChatTone | null;
};

function normalizeAiLocaleTag(raw: string | null | undefined): string {
  const s = String(raw || "").trim().toLowerCase();
  if (!s) return "en";
  if (s.startsWith("zh")) return "zh";
  return s.slice(0, 2) || "en";
}

function resolveAiLocaleOverride(ctx: AiLanguageToneContext | undefined | null): string {
  const raw = String(ctx?.overrideLanguage ?? "").trim();
  if (!raw) return "auto";
  return raw.toLowerCase() === "auto" ? "auto" : raw;
}

function resolveAiLanguageTone(ctx: AiLanguageToneContext | undefined | null): { language: string; tone: ChatTone; languageReason: string } {
  const uiLocale = ctx?.uiLocale ?? getCurrentUiLocale() ?? getStoredLocale() ?? getUiLocaleForAiRequests() ?? "en";
  const languageBase = resolveChatLanguage(ctx?.viewer ?? null, ctx?.partner ?? null, uiLocale);
  const language = (ctx?.overrideLanguage ?? "").trim() || languageBase.language;
  const tone = resolveTone({
    conversationState: ctx?.conversationState ?? "active",
    isFirstMessage: Boolean(ctx?.isFirstMessage),
    override: ctx?.overrideTone ?? null,
  });
  return { language, tone, languageReason: languageBase.reason };
}

async function withAiLanguageFailsafe<T>(
  options: { expectedLanguage: string; maxRetries: number; label: string },
  run: (attempt: number) => Promise<T>,
  extractText: (value: T) => string,
): Promise<T> {
  let lastError: unknown = null;
  for (let attempt = 0; attempt <= options.maxRetries; attempt += 1) {
    try {
      const out = await run(attempt);
      const text = extractText(out);
      const ok = Boolean(text.trim()) && !detectMixedScripts(text) && isTextLikelyInExpectedLanguage(options.expectedLanguage, text);
      if (ok) return out;
      lastError = new Error(`[neyra] ${options.label} failed language check (attempt ${attempt + 1})`);
    } catch (e) {
      lastError = e;
    }
  }
  if (lastError) throw lastError;
  return await run(0);
}

export async function fetchAiReplyOptions(options: {
  lastMessage: string;
  conversationContext: string[];
  userPreferredStyle?: string | null;
  aiCtx?: AiLanguageToneContext;
}): Promise<string[]> {
  const { language } = resolveAiLanguageTone(options.aiCtx);
  return await withAiLanguageFailsafe(
    { expectedLanguage: language, maxRetries: 2, label: "ai-reply-options" },
    async () => {
      // Canonical endpoint (server enforces: always 3, short, question-ending).
      try {
        const raw = await apiFetch("/ai/reply", {
          method: "POST",
          metaReason: "ai-reply",
          skipThrottle: true,
          body: JSON.stringify({
            last_message: String(options.lastMessage || "").trim(),
            conversation_context: (options.conversationContext || []).map((x) => String(x || "").trim()).filter(Boolean).slice(-10),
            user_preferred_style: options.userPreferredStyle || null,
            locale: language,
          }),
        });
        const rows = raw && typeof raw === "object" ? (raw as any).options : null;
        if (Array.isArray(rows)) return rows.map((x) => String(x || "").trim()).filter(Boolean).slice(0, 3);
      } catch {
        // Back-compat fallback.
      }
      const legacy = await apiFetch("/ai/reply-options", {
        method: "POST",
        metaReason: "ai-reply-options",
        skipThrottle: true,
        body: JSON.stringify({
          last_message: String(options.lastMessage || "").trim(),
          conversation_context: (options.conversationContext || []).map((x) => String(x || "").trim()).filter(Boolean).slice(-10),
          user_preferred_style: options.userPreferredStyle || null,
          locale: language,
        }),
      });
      const rows = legacy && typeof legacy === "object" ? (legacy as any).options : null;
      if (!Array.isArray(rows)) return [];
      return rows.map((x) => String(x || "").trim()).filter(Boolean).slice(0, 3);
    },
    (rows) => rows.join(" "),
  );
}

export type ChatCopilotOption = { label: string; text: string };
export type ChatCopilotStall = { is_stalled: boolean; stall_score: number; reasons: string[] };
export type ChatCopilotResponse = {
  strategy: string | null;
  meeting_readiness: number | null;
  meeting_suggestion: string | null;
  best_option_index?: number;
  options: ChatCopilotOption[];
  safety_notes: string[];
  limited?: boolean;
  stall?: ChatCopilotStall | null;
  /** Server used deterministic copy while live AI was unavailable — still a normal 200 response. */
  fallback?: boolean;
  source?: string | null;
  locale?: string | null;
};

export type StartStrategyOpener = { style: "light" | "flirty" | "curious"; text: string };
export type StartStrategyResponse = {
  strategy: string | null;
  confidence: number | null;
  hooks: string[];
  openers: StartStrategyOpener[];
};

export async function fetchStartStrategy(options: { partnerUserId: number; messages?: string[] }): Promise<StartStrategyResponse | null> {
  const locale = String(getCurrentUiLocale() || getStoredLocale() || "en").trim() || "en";
  const language = locale;
  const raw = await apiFetch("/ai/start-strategy", {
    method: "POST",
    metaReason: "ai-start-strategy",
    skipThrottle: true,
    body: JSON.stringify({
      partner_user_id: Math.trunc(Number(options.partnerUserId)),
      messages: (options.messages || []).map((x) => String(x || "").trim()).filter(Boolean).slice(0, 3),
      locale,
      language,
    }),
  });
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as any;
  const rows = Array.isArray(obj.openers) ? obj.openers : [];
  const openers: StartStrategyOpener[] = rows
    .map((o: any) => ({
      style: (String(o?.style || "light").trim() as any) === "flirty" ? "flirty" : (String(o?.style || "light").trim() as any) === "curious" ? "curious" : "light",
      text: String(o?.text || "").trim(),
    }))
    .filter((o: any) => o.text)
    .slice(0, 3);
  return {
    strategy: typeof obj.strategy === "string" ? obj.strategy : null,
    confidence: Number.isFinite(obj.confidence) ? Number(obj.confidence) : null,
    hooks: Array.isArray(obj.hooks) ? obj.hooks.map((x: any) => String(x || "").trim()).filter(Boolean).slice(0, 6) : [],
    openers,
  };
}

export async function fetchChatCopilot(options: {
  partnerUserId: number;
  userSelectedStyle?: string | null;
  aiCtx?: AiLanguageToneContext;
}): Promise<ChatCopilotResponse | null> {
  const resolved = resolveAiLanguageTone(options.aiCtx);
  return await withAiLanguageFailsafe(
    { expectedLanguage: resolved.language, maxRetries: 2, label: "ai-chat-copilot" },
    async () => {
      const raw = await apiFetch("/ai/chat-copilot", {
        method: "POST",
        metaReason: "ai-chat-copilot",
        skipThrottle: true,
        softFail: true,
        body: JSON.stringify({
          partner_user_id: Math.trunc(Number(options.partnerUserId)),
          mode: null,
          user_selected_style: options.userSelectedStyle || null,
          locale: resolved.language,
          ai_locale: resolveAiLocaleOverride(options.aiCtx),
          language: resolved.language,
          tone: resolved.tone,
        }),
      });
      if (raw === undefined || raw === null || typeof raw !== "object") return null;
      const obj = raw as any;
      const opts = Array.isArray(obj.options) ? obj.options : [];
      const stallObj = obj.stall && typeof obj.stall === "object" ? obj.stall : null;
      const stall: ChatCopilotStall | null =
        stallObj && typeof stallObj.is_stalled === "boolean"
          ? {
              is_stalled: Boolean(stallObj.is_stalled),
              stall_score: Number.isFinite(stallObj.stall_score)
                ? Math.max(0, Math.min(100, Math.trunc(Number(stallObj.stall_score))))
                : 0,
              reasons: Array.isArray(stallObj.reasons)
                ? stallObj.reasons.map((x: any) => String(x || "").trim()).filter(Boolean).slice(0, 6)
                : [],
            }
          : null;
      const responseLocale = normalizeAiLocaleTag(typeof obj.locale === "string" ? obj.locale : resolved.language);
      if (responseLocale !== normalizeAiLocaleTag(resolved.language)) {
        throw new Error("ai_locale_mismatch");
      }
      return {
        strategy: typeof obj.strategy === "string" ? obj.strategy : null,
        meeting_readiness: Number.isFinite(obj.meeting_readiness) ? Number(obj.meeting_readiness) : null,
        meeting_suggestion: typeof obj.meeting_suggestion === "string" ? obj.meeting_suggestion : null,
        best_option_index: Number.isFinite(obj.best_option_index) ? Math.max(0, Math.min(2, Math.trunc(Number(obj.best_option_index)))) : 0,
        options: opts
          .map((o: any) => ({ label: String(o?.label || "").trim(), text: String(o?.text || "").trim() }))
          .filter((o: any) => o.text)
          .slice(0, 3),
        safety_notes: Array.isArray(obj.safety_notes)
          ? obj.safety_notes.map((x: any) => String(x || "").trim()).filter(Boolean).slice(0, 6)
          : [],
        limited: Boolean(obj.limited),
        stall,
        fallback: Boolean(obj.fallback),
        source: typeof obj.source === "string" ? obj.source : obj.source == null ? null : String(obj.source),
        locale: responseLocale,
      };
    },
    (pack) => (pack?.options ?? []).map((o) => o.text).join(" "),
  );
}

/** Modes accepted by POST /ai/chat-brain/suggestions (UI "Deep" → deepen). "auto" = server picks from context. */
export type ChatBrainMode = "opener" | "reply" | "revive" | "deepen" | "flirty";
export type ChatBrainRequestMode = ChatBrainMode | "auto";
export type ChatBrainVariantKey = "light" | "flirty" | "deep";

export type ChatBrainCoachAction = "write_now" | "wait" | "change_style";

export type ChatBrainCoaching = {
  action: ChatBrainCoachAction;
  hint_key?: string;
  premium_teaser_key?: string;
};

export type ChatBrainUI = {
  suggestions_visible: boolean;
  wait_phase?: "hard" | "soft" | null;
};

export type ChatBrainVariantInsight = {
  risk: "safe" | "neutral" | "risky";
  tip_key: string;
};

export type ChatBrainRecoReason = "easy_not_spam" | "invites_reply" | "fits_context";

export type ConversationRelationshipStage =
  | "opener"
  | "warmup"
  | "engaged"
  | "flirty"
  | "connection"
  | "meeting_ready";

export type DatingStrategyNextAction = "continue" | "flirt" | "deepen" | "suggest_meet" | "wait";

export type DatingStrategyMeta = {
  next_action: DatingStrategyNextAction;
  reasoning_tags: string[];
};

export type CoachScoreMeta = {
  interest_score: number;
  momentum_score: number;
  stall_risk: number;
  flirt_readiness: number;
  meeting_readiness: number;
  recommended_move: string;
  reason: string;
  warning?: string | null;
  meeting_readiness_meta?: "not_ready" | "warming_up" | "ready_soft" | "ready_direct";
  casual_meeting_line?: string | null;
};

export type ChatBrainStylePublic = {
  adapting: boolean;
  top_style: ChatBrainVariantKey | null;
  preferred_tone: string;
  emoji_preference: string;
  avg_message_length: string;
  reply_after_brain_rate: number | null;
};

export type ChatBrainSuggestionsMeta = {
  mode: string;
  language: string;
  regenerate_variant: ChatBrainVariantKey | null;
  ai_used: boolean;
  requested_mode?: string;
  mode_resolution?: string;
  context_mode?: string;
  visible_modes?: string[];
  text_message_count?: number;
  style_public?: ChatBrainStylePublic;
  /** Relationship stage engine (distinct from topic-brain conversation_stage). */
  relationship_stage?: ConversationRelationshipStage | null;
  stage_mutuality_score?: number | null;
  stage_energy_score?: number | null;
  suggested_tone?: string | null;
  suggested_conversation_mode?: string | null;
  dating_strategy?: DatingStrategyMeta | null;
  coach_score?: CoachScoreMeta | null;
  quality?: Partial<Record<ChatBrainVariantKey, { quality_score: number; quality_flags: string[] }>>;
  /** Topic / readiness stage label from chat-brain (server meta). */
  conversation_stage?: string | null;
  conversation_mode?: string | null;
};

export type ChatBrainSuggestionsResponse = {
  ok: true;
  variants: Record<ChatBrainVariantKey, string>;
  coaching: ChatBrainCoaching;
  ui: ChatBrainUI;
  recommended_variant: ChatBrainVariantKey | null;
  recommendation_reason: ChatBrainRecoReason | null;
  variant_insights: Partial<Record<ChatBrainVariantKey, ChatBrainVariantInsight>>;
  meta: ChatBrainSuggestionsMeta;
};

const CHAT_BRAIN_MEMO_TTL_MS = 120_000;

/** Test hook: reset memo/inflight for duplicate-call assertions. */
export function __resetChatBrainSuggestionsDedupeForTests(): void {
  chatBrainSuggestionsMemo.clear();
  chatBrainSuggestionsInflight.clear();
}

/** Deterministic cache key (same logical POST body regardless of field insertion order). */
export function stableChatBrainMemoKey(body: Record<string, unknown>): string {
  return Object.keys(body)
    .sort()
    .map((k) => `${k}:${JSON.stringify(body[k])}`)
    .join("|");
}

/** Maps UI dating strategist mode → POST /ai/chat-brain/suggestions `conversation_mode`. */
export type DatingConversationMode = "easy" | "flirty" | "funny" | "deep" | "confident" | "romantic" | "playful" | "pickup_master";

export function mapDatingConversationModeToApi(mode: DatingConversationMode, isPremiumTier: boolean): string {
  if (mode === "pickup_master") return isPremiumTier ? "premium_pickup_master" : "confident";
  if (mode === "funny") return "playful";
  return mode;
}

export type ConversationStageResponse = {
  stage: ConversationRelationshipStage;
  mutuality_score: number;
  energy_score: number;
};

export async function fetchConversationStage(messages: {
  role: "me" | "them";
  text: string;
  created_at?: string | null;
}[]): Promise<ConversationStageResponse | null> {
  const raw = await apiFetch("/ai/conversation-stage", {
    method: "POST",
    metaReason: "conversation-stage",
    skipThrottle: true,
    body: JSON.stringify({ messages: (messages || []).slice(-80) }),
  });
  if (!raw || typeof raw !== "object") return null;
  const o = raw as any;
  const st = o.stage;
  const stage: ConversationRelationshipStage | null =
    st === "opener" ||
    st === "warmup" ||
    st === "engaged" ||
    st === "flirty" ||
    st === "connection" ||
    st === "meeting_ready"
      ? st
      : null;
  if (!stage) return null;
  const mutuality_score =
    typeof o.mutuality_score === "number" && Number.isFinite(o.mutuality_score)
      ? Math.max(0, Math.min(1, Number(o.mutuality_score)))
      : 0;
  const energy_score =
    typeof o.energy_score === "number" && Number.isFinite(o.energy_score)
      ? Math.max(0, Math.min(1, Number(o.energy_score)))
      : 0;
  return { stage, mutuality_score, energy_score };
}

export async function postChatBrainSuggestions(options: {
  partnerUserId: number;
  mode: ChatBrainRequestMode;
  tone?: string;
  language: string;
  conversationMode?: DatingConversationMode;
  isPremiumTier?: boolean;
  aiCtx?: AiLanguageToneContext;
  regenerateVariant?: ChatBrainVariantKey | null;
  peerVariants?: Partial<Record<ChatBrainVariantKey, string>> | null;
  signal?: AbortSignal;
}): Promise<ChatBrainSuggestionsResponse> {
  const uiLocale = String(getCurrentUiLocale() || getUiLocaleForAiRequests() || "en").trim() || "en";
  const peer = options.peerVariants || {};
  const resolved = resolveAiLanguageTone(options.aiCtx);
  const explicitLang =
    String(
      (options.aiCtx?.overrideLanguage ?? "").trim() ||
        (options.aiCtx?.uiLocale ?? "").trim() ||
        (options.language || "").trim() ||
        resolved.language ||
        uiLocale ||
        "en",
    ).trim() || "en";
  const { language_hint } = getAiLocalePayload();
  neyraAiLocaleDevLog("requesting suggestions", {
    endpoint: "chat-brain/suggestions",
    locale: explicitLang,
    partnerUserId: options.partnerUserId,
    mode: options.mode,
  });
  const premiumTier = Boolean(options.isPremiumTier);
  const conv = mapDatingConversationModeToApi(options.conversationMode ?? "easy", premiumTier);
  const body: Record<string, unknown> = {
    partner_user_id: Math.trunc(Number(options.partnerUserId)),
    mode: options.mode,
    tone: (options.tone ?? resolved.tone ?? "auto").trim() || "auto",
    language: explicitLang,
    ai_locale: resolveAiLocaleOverride(options.aiCtx),
    language_hint,
    conversation_mode: conv,
  };
  const regen = options.regenerateVariant;
  if (regen === "light" || regen === "flirty" || regen === "deep") {
    body.regenerate_variant = regen;
    body.peer_variants = {
      light: String(peer.light ?? ""),
      flirty: String(peer.flirty ?? ""),
      deep: String(peer.deep ?? ""),
    };
  }

  const memoKey = stableChatBrainMemoKey(body);
  const memoHit = chatBrainSuggestionsMemo.get(memoKey);
  if (memoHit && Date.now() - memoHit.at < CHAT_BRAIN_MEMO_TTL_MS) {
    // Memo key already scopes by `language`; keep only a guard for wrong-type cache entries.
    return memoHit.res as ChatBrainSuggestionsResponse;
  }
  const inflightHit = chatBrainSuggestionsInflight.get(memoKey);
  if (inflightHit) return inflightHit as Promise<ChatBrainSuggestionsResponse>;

  const expectedLang = String(body.language || "en").trim() || "en";
  const localeAtStart = uiLocale;

  const run = (async (): Promise<ChatBrainSuggestionsResponse> => {
  let raw: unknown = undefined;
  for (let netAttempt = 0; netAttempt < 2; netAttempt++) {
    raw = await apiFetch("/ai/chat-brain/suggestions", {
      method: "POST",
      metaReason: netAttempt === 0 ? "chat-brain-suggestions" : "chat-brain-suggestions:network_retry",
      skipThrottle: true,
      softFail: true,
      signal: options.signal,
      body: JSON.stringify(body),
    });
    if (raw !== undefined) break;
  }
  if (!raw || typeof raw !== "object") {
    throw new Error("ai_unavailable");
  }
  const obj = raw as any;
  if (!obj.ok) {
    throw new Error(typeof obj.error === "string" ? obj.error : "Chat brain request failed");
  }
  const v = obj.variants && typeof obj.variants === "object" ? obj.variants : {};
  const variants: Record<ChatBrainVariantKey, string> = {
    light: String(v.light ?? "").trim(),
    flirty: String(v.flirty ?? "").trim(),
    deep: String(v.deep ?? "").trim(),
  };
  const metaRaw = obj.meta && typeof obj.meta === "object" ? obj.meta : {};
  const regenMeta = metaRaw.regenerate_variant;
  const spRaw = metaRaw.style_public && typeof metaRaw.style_public === "object" ? metaRaw.style_public : null;
  const ts = spRaw && (spRaw as any).top_style;
  const style_public: ChatBrainStylePublic | undefined = spRaw
    ? {
        adapting: Boolean((spRaw as any).adapting),
        top_style: ts === "light" || ts === "flirty" || ts === "deep" ? ts : null,
        preferred_tone: String((spRaw as any).preferred_tone || "mixed"),
        emoji_preference: String((spRaw as any).emoji_preference || "medium"),
        avg_message_length: String((spRaw as any).avg_message_length || "medium"),
        reply_after_brain_rate:
          typeof (spRaw as any).reply_after_brain_rate === "number" && Number.isFinite((spRaw as any).reply_after_brain_rate)
            ? Number((spRaw as any).reply_after_brain_rate)
            : null,
      }
    : undefined;

  const rs = metaRaw.relationship_stage;
  const relationship_stage: ConversationRelationshipStage | null =
    rs === "opener" ||
    rs === "warmup" ||
    rs === "engaged" ||
    rs === "flirty" ||
    rs === "connection" ||
    rs === "meeting_ready"
      ? rs
      : null;
  const sm = metaRaw.stage_mutuality_score;
  const se = metaRaw.stage_energy_score;
  const dsRaw = metaRaw.dating_strategy;
  let dating_strategy: DatingStrategyMeta | null = null;
  if (dsRaw && typeof dsRaw === "object") {
    const na = String((dsRaw as any).next_action || "").trim();
    const next_action: DatingStrategyNextAction | null =
      na === "continue" || na === "flirt" || na === "deepen" || na === "suggest_meet" || na === "wait" ? na : null;
    const rt = (dsRaw as any).reasoning_tags;
    const reasoning_tags = Array.isArray(rt) ? rt.map((x: any) => String(x || "").trim()).filter(Boolean) : [];
    if (next_action) {
      dating_strategy = { next_action, reasoning_tags };
    }
  }
  const coachMetaRaw = metaRaw.coach_score && typeof metaRaw.coach_score === "object" ? metaRaw.coach_score : null;
  const coach_score: CoachScoreMeta | null = coachMetaRaw
    ? {
        interest_score: Math.max(0, Math.min(100, Math.round(Number((coachMetaRaw as any).interest_score ?? 0)))),
        momentum_score: Math.max(0, Math.min(100, Math.round(Number((coachMetaRaw as any).momentum_score ?? 0)))),
        stall_risk: Math.max(0, Math.min(100, Math.round(Number((coachMetaRaw as any).stall_risk ?? 0)))),
        flirt_readiness: Math.max(0, Math.min(100, Math.round(Number((coachMetaRaw as any).flirt_readiness ?? 0)))),
        meeting_readiness: Math.max(0, Math.min(100, Math.round(Number((coachMetaRaw as any).meeting_readiness ?? 0)))),
        recommended_move: String((coachMetaRaw as any).recommended_move || "reply"),
        reason: String((coachMetaRaw as any).reason || ""),
        warning: typeof (coachMetaRaw as any).warning === "string" ? String((coachMetaRaw as any).warning) : null,
        meeting_readiness_meta:
          (coachMetaRaw as any).meeting_readiness_meta === "warming_up" ||
          (coachMetaRaw as any).meeting_readiness_meta === "ready_soft" ||
          (coachMetaRaw as any).meeting_readiness_meta === "ready_direct"
            ? (coachMetaRaw as any).meeting_readiness_meta
            : "not_ready",
        casual_meeting_line:
          typeof (coachMetaRaw as any).casual_meeting_line === "string" ? String((coachMetaRaw as any).casual_meeting_line) : null,
      }
    : null;
  const qualityRaw = metaRaw.quality && typeof metaRaw.quality === "object" ? metaRaw.quality : {};
  const quality: ChatBrainSuggestionsMeta["quality"] = {};
  (["light", "flirty", "deep"] as ChatBrainVariantKey[]).forEach((k) => {
    const q = (qualityRaw as any)[k];
    if (!q || typeof q !== "object") return;
    quality[k] = {
      quality_score: Math.max(0, Math.min(100, Math.round(Number(q.quality_score ?? 0)))),
      quality_flags: Array.isArray(q.quality_flags) ? q.quality_flags.map((x: any) => String(x || "").trim()).filter(Boolean) : [],
    };
  });

  const meta: ChatBrainSuggestionsMeta = {
    mode: String(metaRaw.mode ?? options.mode),
    language: String(metaRaw.language ?? options.language),
    regenerate_variant:
      regenMeta === "light" || regenMeta === "flirty" || regenMeta === "deep" ? regenMeta : null,
    ai_used: Boolean(metaRaw.ai_used),
    requested_mode: typeof metaRaw.requested_mode === "string" ? metaRaw.requested_mode : undefined,
    mode_resolution: typeof metaRaw.mode_resolution === "string" ? metaRaw.mode_resolution : undefined,
    context_mode: typeof metaRaw.context_mode === "string" ? metaRaw.context_mode : undefined,
    visible_modes: Array.isArray(metaRaw.visible_modes) ? metaRaw.visible_modes.map((x: any) => String(x)) : undefined,
    text_message_count:
      typeof metaRaw.text_message_count === "number" && Number.isFinite(metaRaw.text_message_count)
        ? Math.trunc(metaRaw.text_message_count)
        : undefined,
    style_public,
    relationship_stage,
    stage_mutuality_score:
      typeof sm === "number" && Number.isFinite(sm) ? Math.max(0, Math.min(1, Number(sm))) : null,
    stage_energy_score:
      typeof se === "number" && Number.isFinite(se) ? Math.max(0, Math.min(1, Number(se))) : null,
    suggested_tone: typeof metaRaw.suggested_tone === "string" ? metaRaw.suggested_tone : null,
    suggested_conversation_mode:
      typeof metaRaw.suggested_conversation_mode === "string" ? metaRaw.suggested_conversation_mode : null,
    dating_strategy,
    coach_score,
    quality,
  };

  if (typeof process !== "undefined" && process.env.NODE_ENV === "development") {
    const responseLocale = String(meta.language || "").trim() || expectedLang;
    console.info("[chat-ai-locale]", { uiLocale: localeAtStart, responseLocale });
  }
  neyraAiLocaleDevLog("received suggestions", {
    endpoint: "chat-brain/suggestions",
    locale: expectedLang,
    partnerUserId: options.partnerUserId,
    mode: options.mode,
  });
  // Stale response guard: if UI locale changed mid-flight, ignore this payload.
  if (String(getCurrentUiLocale() || "en") !== String(localeAtStart || "en")) {
    throw new Error("stale_chat_ai_locale");
  }

  const coachRaw = obj.coaching && typeof obj.coaching === "object" ? obj.coaching : {};
  const act = String((coachRaw as any).action || "write_now").trim();
  const hintKey = String((coachRaw as any).hint_key || "").trim();
  const premiumTeaser = String((coachRaw as any).premium_teaser_key || "").trim();
  const coaching: ChatBrainCoaching = {
    action: act === "wait" || act === "change_style" ? act : "write_now",
    hint_key: hintKey || undefined,
    premium_teaser_key: premiumTeaser || undefined,
  };

  const uiRaw = obj.ui && typeof obj.ui === "object" ? obj.ui : {};
  const sv = (uiRaw as any).suggestions_visible;
  const ui: ChatBrainUI = {
    suggestions_visible: sv !== false,
    wait_phase:
      (uiRaw as any).wait_phase === "hard" || (uiRaw as any).wait_phase === "soft"
        ? (uiRaw as any).wait_phase
        : null,
  };

  const rec = obj.recommended_variant;
  const recommended_variant: ChatBrainVariantKey | null =
    rec === "light" || rec === "flirty" || rec === "deep" ? rec : null;

  const rr = obj.recommendation_reason;
  const recommendation_reason: ChatBrainRecoReason | null =
    rr === "easy_not_spam" || rr === "invites_reply" || rr === "fits_context" ? rr : null;

  const insRaw = obj.variant_insights && typeof obj.variant_insights === "object" ? obj.variant_insights : {};
  const variant_insights: Partial<Record<ChatBrainVariantKey, ChatBrainVariantInsight>> = {};
  for (const k of ["light", "flirty", "deep"] as ChatBrainVariantKey[]) {
    const row = (insRaw as any)[k];
    if (!row || typeof row !== "object") continue;
    const risk = String((row as any).risk || "neutral");
    const tip_key = String((row as any).tip_key || "fits_context");
    variant_insights[k] = {
      risk: risk === "safe" || risk === "risky" ? risk : "neutral",
      tip_key,
    };
  }

  return { ok: true, variants, meta, coaching, ui, recommended_variant, recommendation_reason, variant_insights };
  })();

  chatBrainSuggestionsInflight.set(memoKey, run as unknown as Promise<unknown>);
  try {
    const out = await run;
    chatBrainSuggestionsMemo.set(memoKey, { at: Date.now(), res: out as unknown });
    return out;
  } finally {
    chatBrainSuggestionsInflight.delete(memoKey);
  }
}

export async function activatePremiumTrial(reason: "ai_suggestion_clicked" | "sent_3_messages" | "unknown" = "unknown"): Promise<boolean> {
  const raw = await apiFetch("/growth/trial/activate", {
    method: "POST",
    metaReason: "growth-trial-activate",
    skipThrottle: true,
    body: JSON.stringify({ reason }),
  });
  const started = Boolean(raw && typeof raw === "object" ? (raw as any).started : false);
  if (started) {
    void trackAnalyticsEvent("trial_started", { reason, source: "growth_trial_activate" });
  }
  return started;
}

export async function postStartStrategyEvent(payload: {
  name: "opener_shown" | "opener_selected" | "opener_sent" | "opener_edited" | "partner_replied";
  partner_user_id: number;
  style?: "light" | "flirty" | "curious";
  edited?: boolean;
  partner_replied?: boolean;
}): Promise<void> {
  const locale = getStoredLocale() || "en";
  const language = locale;
  await apiFetch("/ai/start-strategy/event", {
    method: "POST",
    metaReason: `ai-start-strategy:${payload.name}`,
    skipThrottle: true,
    body: JSON.stringify({ ...payload, locale, language }),
  });
}

export async function postAiMemoryEvent(payload: {
  event_type:
    | "option_shown"
    | "option_selected"
    | "option_edited"
    | "edited"
    | "message_sent"
    | "partner_replied"
    | "meeting_suggested"
    | "meeting_accepted"
    | "meeting_rejected"
    | "cb_select"
    | "cb_send"
    | "cb_reply"
    | "cb_copy"
    | "cb_regen"
    | "cb_edit";
  partner_user_id?: number | null;
  /** Opaque thread key for analytics (no message text). */
  thread_id?: string | null;
  metadata_json?: Record<string, any>;
}): Promise<void> {
  await apiFetch("/ai/memory/event", {
    method: "POST",
    metaReason: `ai-memory:${payload.event_type}`,
    skipThrottle: true,
    body: JSON.stringify({
      event_type: payload.event_type,
      partner_user_id: payload.partner_user_id ?? null,
      thread_id: payload.thread_id ?? null,
      metadata_json: payload.metadata_json ?? {},
    }),
  });
}

export type TimingDecisionResponse = {
  should_send_now: boolean;
  confidence: number;
  nudge_type: "now" | "wait" | "reengage" | "revive";
  best_time_window: string;
  reasoning: string;
  decision?: "wait" | "now" | "revive" | "escalate";
  metrics: {
    minutes_since_last_message: number;
    avg_partner_reply_minutes: number;
    mutuality_score: number;
    stall_score: number;
  };
};

export async function fetchTimingDecision(options: {
  partnerUserId: number;
  messages?: { role: "me" | "them"; text: string }[];
  lastMessageAt?: string | null;
  messageCount?: number | null;
  replyTimeAvg?: number | null;
  whoSentLast?: "me" | "them" | null;
  conversationLength?: number | null;
  interestStage?: "cold" | "warming" | "engaged" | "ready" | null;
  mutualityScore?: number | null;
  stallScore?: number | null;
}): Promise<TimingDecisionResponse | null> {
  const locale = getStoredLocale() || "en";
  const raw = await apiFetch("/ai/timing-decision", {
    method: "POST",
    metaReason: "ai-timing-decision",
    skipThrottle: true,
    body: JSON.stringify({
      partner_user_id: Math.trunc(Number(options.partnerUserId)),
      messages: (options.messages || []).slice(-80),
      interest_stage: options.interestStage ?? null,
      mutuality_score: options.mutualityScore ?? null,
      stall_score: options.stallScore ?? null,
      locale,
      last_message_at: options.lastMessageAt ?? null,
      message_count: options.messageCount ?? null,
      reply_time_avg: options.replyTimeAvg ?? null,
      who_sent_last: options.whoSentLast ?? null,
      conversation_length: options.conversationLength ?? null,
    }),
  });
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as any;
  const metricsObj = obj.metrics && typeof obj.metrics === "object" ? obj.metrics : {};
  return {
    should_send_now: Boolean(obj.should_send_now),
    confidence: Number.isFinite(obj.confidence) ? Math.max(0, Math.min(100, Math.trunc(Number(obj.confidence)))) : 0,
    nudge_type: (String(obj.nudge_type || "wait").trim() as any) === "now" ? "now" : (String(obj.nudge_type || "wait").trim() as any) === "reengage" ? "reengage" : (String(obj.nudge_type || "wait").trim() as any) === "revive" ? "revive" : "wait",
    best_time_window: String(obj.best_time_window || "").trim(),
    reasoning: String(obj.reasoning || "").trim(),
    decision:
      (String(obj.decision || "").trim() as any) === "escalate"
        ? "escalate"
        : (String(obj.decision || "").trim() as any) === "revive"
          ? "revive"
          : (String(obj.decision || "").trim() as any) === "now"
            ? "now"
            : (String(obj.decision || "").trim() as any) === "wait"
              ? "wait"
              : undefined,
    metrics: {
      minutes_since_last_message: Number.isFinite(metricsObj.minutes_since_last_message) ? Math.max(0, Math.trunc(Number(metricsObj.minutes_since_last_message))) : 0,
      avg_partner_reply_minutes: Number.isFinite(metricsObj.avg_partner_reply_minutes) ? Math.max(0, Math.trunc(Number(metricsObj.avg_partner_reply_minutes))) : 0,
      mutuality_score: Number.isFinite(metricsObj.mutuality_score) ? Math.max(0, Math.min(100, Math.trunc(Number(metricsObj.mutuality_score)))) : 0,
      stall_score: Number.isFinite(metricsObj.stall_score) ? Math.max(0, Math.min(100, Math.trunc(Number(metricsObj.stall_score)))) : 0,
    },
  };
}

export type NextStepOption = { type: "voice" | "date" | "video"; text: string };

export async function fetchNextStep(): Promise<NextStepOption[]> {
  const locale = getStoredLocale() || "en";
  const raw = await apiFetch("/ai/next-step", {
    method: "POST",
    metaReason: "ai-next-step",
    skipThrottle: true,
    body: JSON.stringify({ locale }),
  });
  if (!Array.isArray(raw)) return [];
  return raw
    .map((r: any) => ({ type: String(r?.type || "").trim(), text: String(r?.text || "").trim() }))
    .filter((r: any) => (r.type === "voice" || r.type === "date" || r.type === "video") && r.text)
    .slice(0, 3) as NextStepOption[];
}

export type TimedReplyOption = { style: "light" | "flirty" | "deep"; text: string };
export type TimedRepliesFetchResult = { options: TimedReplyOption[]; source: string; locale: string };
export async function fetchTimedReplies(options: {
  messages: { role: "me" | "them"; text: string }[];
  nudgeType: "now" | "wait" | "reengage" | "revive";
  interestStage?: "cold" | "warming" | "engaged" | "ready" | null;
  mutualityScore?: number | null;
  aiCtx?: AiLanguageToneContext;
  /** Chat thread id (partner user id) for dev logs / cache scoping. */
  partnerUserId?: number | null;
}): Promise<TimedRepliesFetchResult> {
  if (options.nudgeType === "wait") return { options: [], source: "ai", locale: normalizeAiLocaleTag(options.aiCtx?.overrideLanguage || options.aiCtx?.uiLocale || "en") };
  const { locale: defaultAiLocale, language_hint } = getAiLocalePayload();
  const uiLocale = (options.aiCtx?.uiLocale ?? defaultAiLocale) as string;
  const requestedLocale = normalizeAiLocaleTag(options.aiCtx?.overrideLanguage || uiLocale);
  neyraAiLocaleRequestingSuggestions({ locale: uiLocale, threadId: options.partnerUserId ?? null });
  neyraAiLocaleDevLog("requesting suggestions", {
    endpoint: "timed-replies",
    locale: uiLocale,
    nudgeType: options.nudgeType,
    messageCount: (options.messages || []).length,
  });
  const raw = await apiFetch("/ai/timed-replies", {
    method: "POST",
    metaReason: "ai-timed-replies",
    skipThrottle: true,
    softFail: true,
    body: JSON.stringify({
      messages: (options.messages || []).slice(-80),
      nudge_type: options.nudgeType,
      interest_stage: options.interestStage ?? null,
      mutuality_score: options.mutualityScore ?? null,
      locale: requestedLocale,
      ai_locale: resolveAiLocaleOverride(options.aiCtx),
      language_hint,
    }),
  });
  if (raw === undefined || raw === null || typeof raw !== "object") return { options: [], source: "fallback", locale: requestedLocale };
  const obj = raw as any;
  const rows = Array.isArray(obj.options) ? obj.options : [];
  const source = typeof obj.source === "string" ? String(obj.source).trim() : "ai";
  const out = rows
    .map((o: any) => ({
      style: (String(o?.style || "light").trim() as any) === "flirty" ? "flirty" : (String(o?.style || "light").trim() as any) === "deep" ? "deep" : "light",
      text: String(o?.text || "").trim(),
    }))
    .filter((o: any) => o.text)
    .slice(0, 3);
  const responseLocale = normalizeAiLocaleTag(typeof obj.locale === "string" ? obj.locale : requestedLocale);
  if (responseLocale !== requestedLocale) {
    throw new Error("ai_locale_mismatch");
  }
  neyraAiLocaleDevLog("received suggestions", {
    endpoint: "timed-replies",
    locale: uiLocale,
    nudgeType: options.nudgeType,
    count: out.length,
  });
  return { options: out, source: source || "ai", locale: responseLocale };
}

export type MeetingReadinessMessage = { role: "me" | "them"; text: string; ts_ms?: number | null };
export type MeetingOption = { kind: "coffee" | "walk" | "drinks" | "custom" | string; label: string; text: string };
export type CloserStage =
  | "opener"
  | "early_chat"
  | "engaged"
  | "high_interest"
  | "stalled"
  | "ready_for_meeting";

export type MeetingReadinessResponse = {
  stage: "early" | "warming" | "ready" | "stalled";
  score: number;
  reason: string;
  suggested_action: "keep_chatting" | "ask_deeper" | "suggest_meeting" | "revive";
  meeting_options: MeetingOption[];
  /** Same as `score` (0–100); preferred for new UI. */
  readiness_score?: number;
  closer_stage?: CloserStage | string;
  closer_suggestions?: string[];
  show_moment_hint?: boolean;
  // back-compat
  meeting_readiness?: number;
  reasoning?: string[];
  risk_level?: "low" | "medium" | "high";
};

export type MeetingReadyResponse = {
  readiness_score: number;
  closer_stage: string;
  suggestions: string[];
  show_moment_hint: boolean;
};

export async function fetchMeetingReadiness(options: {
  partnerUserId: number;
  messages: MeetingReadinessMessage[];
  city?: string | null;
  markShown?: boolean;
  aiCtx?: AiLanguageToneContext;
}): Promise<MeetingReadinessResponse | null> {
  const { language } = resolveAiLanguageTone(options.aiCtx);
  const raw = await apiFetch("/ai/meeting-readiness", {
    method: "POST",
    metaReason: "ai-meeting-readiness",
    skipThrottle: true,
    body: JSON.stringify({
      partner_user_id: Math.trunc(Number(options.partnerUserId)),
      city: String(options.city || "").trim() || null,
      mark_shown: Boolean(options.markShown),
      messages: (options.messages || [])
        .map((m) => ({ role: m.role, text: String(m.text || "").trim(), ts_ms: m.ts_ms == null ? null : Math.trunc(Number(m.ts_ms)) }))
        .filter((m) => m.text)
        .slice(-20),
      locale: language,
    }),
  });
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as any;
  const stageRaw = String(obj.stage || "").trim().toLowerCase();
  const stage =
    stageRaw === "early" || stageRaw === "warming" || stageRaw === "ready" || stageRaw === "stalled"
      ? (stageRaw as any)
      : null;
  const score = Number.isFinite(obj.score) ? Math.max(0, Math.min(100, Math.trunc(Number(obj.score)))) : null;
  if (!stage || score == null) return null;
  const suggestedRaw = String(obj.suggested_action || "").trim().toLowerCase();
  const suggested_action =
    suggestedRaw === "keep_chatting" || suggestedRaw === "ask_deeper" || suggestedRaw === "suggest_meeting" || suggestedRaw === "revive"
      ? (suggestedRaw as any)
      : stage === "ready"
        ? "suggest_meeting"
        : stage === "warming"
          ? "ask_deeper"
          : stage === "stalled"
            ? "revive"
            : "keep_chatting";
  const meeting_options = Array.isArray(obj.meeting_options)
    ? obj.meeting_options
        .map((o: any) => ({
          kind: String(o?.kind || "").trim() || "custom",
          label: String(o?.label || "").trim() || "",
          text: String(o?.text || "").trim() || "",
        }))
        .filter((o: any) => o.text)
        .slice(0, 4)
    : [];
  const readiness_score = Number.isFinite(obj.readiness_score)
    ? Math.max(0, Math.min(100, Math.trunc(Number(obj.readiness_score))))
    : score;
  const closer_raw = String(obj.closer_stage || "").trim().toLowerCase();
  const closer_stage =
    closer_raw === "opener" ||
    closer_raw === "early_chat" ||
    closer_raw === "engaged" ||
    closer_raw === "high_interest" ||
    closer_raw === "stalled" ||
    closer_raw === "ready_for_meeting"
      ? (closer_raw as CloserStage)
      : undefined;
  const closer_suggestions = Array.isArray(obj.closer_suggestions)
    ? obj.closer_suggestions.map((x: any) => String(x || "").trim()).filter(Boolean).slice(0, 3)
    : undefined;

  return {
    stage,
    score,
    reason: String(obj.reason || "").trim(),
    suggested_action,
    meeting_options,
    readiness_score,
    closer_stage,
    closer_suggestions,
    show_moment_hint: Boolean(obj.show_moment_hint),
    meeting_readiness: Number.isFinite(obj.meeting_readiness) ? Math.max(0, Math.min(100, Math.trunc(Number(obj.meeting_readiness)))) : undefined,
    reasoning: Array.isArray(obj.reasoning) ? obj.reasoning.map((x: any) => String(x || "").trim()).filter(Boolean).slice(0, 6) : undefined,
    risk_level: (String(obj.risk_level || "").trim().toLowerCase() === "low" || String(obj.risk_level || "").trim().toLowerCase() === "high"
      ? String(obj.risk_level || "").trim().toLowerCase()
      : "medium") as any,
  };
}

export async function fetchMeetingReady(options: {
  partnerUserId: number;
  messages: MeetingReadinessMessage[];
  city?: string | null;
  aiCtx?: AiLanguageToneContext;
}): Promise<MeetingReadyResponse | null> {
  const { language } = resolveAiLanguageTone(options.aiCtx);
  const raw = await apiFetch("/ai/meeting-ready", {
    method: "POST",
    metaReason: "ai-meeting-ready",
    skipThrottle: true,
    body: JSON.stringify({
      partner_user_id: Math.trunc(Number(options.partnerUserId)),
      city: String(options.city || "").trim() || null,
      messages: (options.messages || [])
        .map((m) => ({ role: m.role, text: String(m.text || "").trim(), ts_ms: m.ts_ms == null ? null : Math.trunc(Number(m.ts_ms)) }))
        .filter((m) => m.text)
        .slice(-20),
      locale: language,
    }),
  });
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as any;
  const readiness_score = Number.isFinite(obj.readiness_score) ? Math.max(0, Math.min(100, Math.trunc(Number(obj.readiness_score)))) : null;
  if (readiness_score == null) return null;
  const suggestions = Array.isArray(obj.suggestions)
    ? obj.suggestions.map((x: any) => String(x || "").trim()).filter(Boolean).slice(0, 3)
    : [];
  return {
    readiness_score,
    closer_stage: String(obj.closer_stage || "").trim() || "early_chat",
    suggestions,
    show_moment_hint: Boolean(obj.show_moment_hint),
  };
}

export type ConversationQualityMessage = { role: "me" | "them"; text: string; ts_ms?: number | null };
export type ConversationQualityResponse = { score: number; status: "cold" | "warm" | "hot" };

export async function fetchConversationQuality(options: {
  messages: ConversationQualityMessage[];
  aiCtx?: AiLanguageToneContext;
}): Promise<ConversationQualityResponse | null> {
  const { language } = resolveAiLanguageTone(options.aiCtx);
  const raw = await apiFetch("/ai/conversation-quality", {
    method: "POST",
    metaReason: "ai-conversation-quality",
    skipThrottle: true,
    body: JSON.stringify({
      messages: (options.messages || [])
        .map((m) => ({
          role: m.role,
          text: String(m.text || "").trim(),
          ts_ms: m.ts_ms == null ? null : Math.trunc(Number(m.ts_ms)),
        }))
        .filter((m) => m.text)
        .slice(-80),
      locale: language,
    }),
  });
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as any;
  const score = Number.isFinite(obj.score) ? Math.max(0, Math.min(100, Math.trunc(Number(obj.score)))) : null;
  if (score == null) return null;
  const statusRaw = String(obj.status || "").trim().toLowerCase();
  const status = statusRaw === "hot" || statusRaw === "warm" || statusRaw === "cold" ? (statusRaw as any) : "warm";
  return { score, status };
}

export async function fetchMeetingOptions(options: {
  messages: MeetingReadinessMessage[];
  meetingReadiness: number;
  aiCtx?: AiLanguageToneContext;
}): Promise<string[]> {
  const { language } = resolveAiLanguageTone(options.aiCtx);
  const raw = await apiFetch("/ai/meeting-options", {
    method: "POST",
    metaReason: "ai-meeting-options",
    skipThrottle: true,
    body: JSON.stringify({
      messages: (options.messages || [])
        .map((m) => ({ role: m.role, text: String(m.text || "").trim() }))
        .filter((m) => m.text)
        .slice(-80),
      meeting_readiness: Math.max(0, Math.min(100, Math.trunc(Number(options.meetingReadiness || 0)))),
      locale: language,
    }),
  });
  const rows = raw && typeof raw === "object" ? (raw as any).meeting_options : null;
  if (!Array.isArray(rows)) return [];
  return rows.map((x: any) => String(x || "").trim()).filter(Boolean).slice(0, 3);
}

export async function postAiLearningEvent(payload: {
  name: "ai_options_shown" | "ai_option_selected" | "ai_option_sent";
  style?: "light" | "flirty" | "deep";
  index?: number;
  edited?: boolean;
  final_text?: string;
}): Promise<void> {
  await apiFetch("/ai/learning/event", {
    method: "POST",
    metaReason: `ai-learning:${payload.name}`,
    skipThrottle: true,
    body: JSON.stringify(payload),
  });
}

type ChatRequestOptions = {
  signal?: AbortSignal;
};

type FetchConversationsOptions = ChatRequestOptions;

export function emitChatSync(detail: ChatSyncDetail) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<ChatSyncDetail>(CHAT_SYNC_EVENT, { detail }));
}

export function emitViewerRefresh(reason: string) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(VIEWER_REFRESH_EVENT, { detail: { reason } }));
}

function invalidateChatSummaryCaches() {
  invalidateApiGetCache("/messages/conversations");
  invalidateApiGetCache("/nav/badges");
  invalidateApiGetCache("/matches");
}

function invalidateChatThreadCache(partnerUserId: number) {
  invalidateApiGetCache(`/messages/${partnerUserId}`);
}

export function hasChatSession(): boolean {
  return Boolean(getToken());
}

export function invalidateChatCaches(partnerUserId?: number) {
  invalidateChatSummaryCaches();
  if (partnerUserId != null) invalidateChatThreadCache(partnerUserId);
}

export async function fetchChatViewer(options: ChatRequestOptions = {}): Promise<ChatViewer | null> {
  const raw = await apiFetch("/auth/me", {
    metaReason: "chat-viewer",
    signal: options.signal,
    skipThrottle: true,
  });
  return normalizeChatViewer(raw);
}

function bypassConversationsClientThrottle(reason: string): boolean {
  return (
    reason === "chat-inbox-retry" ||
    reason === "chat-inbox-manual" ||
    reason.startsWith("chat-inbox-manual")
  );
}

export async function fetchChatConversations(
  reason: string,
  options: FetchConversationsOptions = {},
): Promise<ChatConversation[]> {
  const { signal } = options;

  debugChat("conversations fetch start", { reason });

  const raw = await apiFetch("/messages/conversations", {
    metaReason: reason,
    signal,
    skipCache: reason === "chat-inbox-retry" || reason.startsWith("chat-inbox-manual"),
    skipThrottle: bypassConversationsClientThrottle(reason),
  });
  debugChat("conversations API raw", {
    reason,
    kind: raw == null ? "null" : Array.isArray(raw) ? "array" : typeof raw,
    length: Array.isArray(raw) ? raw.length : undefined,
    topKeys:
      raw && typeof raw === "object" && !Array.isArray(raw) ? Object.keys(raw as object).slice(0, 24) : undefined,
  });
  const mapped = normalizeConversationsPayload(raw);
  debugChat("conversations mapped state", {
    reason,
    count: mapped.length,
    partnerUserIds: mapped.map((c) => c.partnerUserId),
    matchIds: mapped.map((c) => c.matchId),
  });
  return mapped;
}

export async function fetchThreadPartnerProfile(
  partnerUserId: number,
  options: ChatRequestOptions = {},
): Promise<ChatPartnerProfile | null> {
  const raw = await apiFetch(`/profiles/partner/${partnerUserId}`, {
    metaReason: `chat-partner-${partnerUserId}`,
    signal: options.signal,
    skipThrottle: true,
  });
  return normalizePartnerProfile(raw);
}

export async function fetchThreadMessages(
  partnerUserId: number,
  reason: string,
  options: ChatRequestOptions & { limit?: number; offset?: number } = {},
) {
  const pid = Math.trunc(Number(partnerUserId));
  const allowParallel = reason === "chat-thread-manual" || reason === "chat-thread-older";
  if (!allowParallel && !options.signal) {
    const existing = threadMessagesInflight.get(pid);
    if (existing) return existing;
  }

  const job = (async () => {
    const qs = new URLSearchParams();
    if (options.limit != null) qs.set("limit", String(options.limit));
    if (options.offset != null) qs.set("offset", String(options.offset));
    const q = qs.toString();
    const raw = await apiFetch(`/messages/${partnerUserId}${q ? `?${q}` : ""}`, {
      metaReason: reason,
      signal: options.signal,
      skipCache: reason === "chat-thread-manual" || reason === "chat-thread-older",
      skipThrottle: reason !== "chat-thread-poll",
    });
    const normalized = normalizeThreadFetch(raw);
    if (THREAD_FETCH_DEBUG) {
      const n = (threadFetchCountsByPartner.get(pid) ?? 0) + 1;
      threadFetchCountsByPartner.set(pid, n);
      debugChat("thread fetch completed", { partnerUserId: pid, reason, completedFetchCount: n });
    }
    return normalized;
  })();

  if (!allowParallel && !options.signal) {
    threadMessagesInflight.set(pid, job);
    void job.finally(() => {
      if (threadMessagesInflight.get(pid) === job) threadMessagesInflight.delete(pid);
    });
  }

  return job;
}

/** Server creates first message in an empty thread (personalized opener, `ai_generated` flag). */
export async function postAiConversationOpener(partnerUserId: number, locale?: string | null): Promise<void> {
  const loc = String(locale || getCurrentUiLocale() || "en").trim() || "en";
  await apiFetch("/messages/ai-opener", {
    method: "POST",
    body: JSON.stringify({ receiver_id: Math.trunc(Number(partnerUserId)), locale: loc }),
    metaReason: "chat-ai-auto-opener",
    skipThrottle: true,
  });
}

export async function deleteChatByMatchId(matchId: number): Promise<void> {
  await apiFetch(`/chats/${Math.trunc(Number(matchId))}`, { method: "DELETE", skipThrottle: true });
  invalidateChatCaches();
}

export type VoiceUploadResult = {
  url: string;
  resolvedUrl: string;
  content_type: string;
  bytes: number;
  duration_ms: number | null;
};

export async function uploadVoiceNote(blob: Blob, options: { filename?: string } = {}): Promise<VoiceUploadResult> {
  const filename =
    options.filename ||
    (blob.type.includes("mp4") || blob.type.includes("m4a") ? "voice.m4a" : blob.type.includes("aac") ? "voice.aac" : "voice.webm");
  const form = new FormData();
  form.append("file", blob, filename);
  const raw = await apiUpload("/uploads/voice", form, { metaReason: "chat-voice-upload" });
  const url = raw && typeof raw === "object" ? String((raw as any).url || "") : "";
  if (!url) throw new Error("Voice upload failed.");
  return {
    url,
    resolvedUrl: resolveMediaUrl(url),
    content_type: raw && typeof raw === "object" ? String((raw as any).content_type || "") : "",
    bytes: raw && typeof raw === "object" ? Number((raw as any).bytes || 0) : 0,
    duration_ms: raw && typeof raw === "object" ? (Number.isFinite((raw as any).duration_ms) ? Number((raw as any).duration_ms) : null) : null,
  };
}

type VoiceAttachment = {
  voice_url: string;
  voice_mime?: string | null;
  voice_duration_ms?: number | null;
};

/** Privacy-safe assist attribution on send (backend AssistMetaPayload). */
export type MessageAssistMeta = {
  kind: "suggestion" | "rewrite";
  mode: string;
  source: string;
  variant?: string | null;
  brain_mode?: string | null;
  was_recommended?: boolean | null;
  conversation_stage?: string | null;
  conversation_mode?: string | null;
  edited_after_insert?: boolean | null;
};

/** Aligns with backend MessageCreate: receiver_id (int), content (optional when voice_url is present), conversation_context (list[str]). */
function buildMessageCreatePayload(
  partnerUserId: number,
  content: string,
  conversationContext: string[],
  replyToMessageId?: string | null,
  voice?: VoiceAttachment | null,
  idempotencyKey?: string | null,
  assistMeta?: MessageAssistMeta | null,
): {
  receiver_id: number;
  content: string;
  conversation_context: string[];
  reply_to_message_id?: number;
  voice_url?: string;
  voice_mime?: string | null;
  voice_duration_ms?: number | null;
  idempotency_key?: string;
  assist_meta?: Record<string, unknown>;
} {
  const receiver_id = Math.trunc(Number(partnerUserId));
  if (!Number.isFinite(receiver_id) || receiver_id < 1) {
    throw new Error("Invalid recipient — open this chat from your inbox or matches.");
  }

  const trimmed = (content ?? "").trim();
  const voice_url = (voice?.voice_url ?? "").trim();
  if (!trimmed && !voice_url) throw new Error("Message cannot be empty.");

  const conversation_context = (Array.isArray(conversationContext) ? conversationContext : [])
    .map((line) => String(line ?? "").trim())
    .filter(Boolean)
    .map((line) => (line.length > 8_000 ? line.slice(0, 8_000) : line))
    .slice(-15);

  const reply_to_message_id =
    replyToMessageId != null && String(replyToMessageId).trim()
      ? Math.trunc(Number(replyToMessageId))
      : null;
  const body: {
    receiver_id: number;
    content: string;
    conversation_context: string[];
    reply_to_message_id?: number;
    voice_url?: string;
    voice_mime?: string | null;
    voice_duration_ms?: number | null;
    idempotency_key?: string;
    assist_meta?: Record<string, unknown>;
  } = {
    receiver_id,
    content: trimmed,
    conversation_context,
  };
  if (reply_to_message_id && Number.isFinite(reply_to_message_id) && reply_to_message_id > 0) {
    body.reply_to_message_id = reply_to_message_id;
  }
  if (voice_url) {
    body.voice_url = voice_url;
    if (voice?.voice_mime) body.voice_mime = voice.voice_mime;
    if (voice?.voice_duration_ms != null) body.voice_duration_ms = voice.voice_duration_ms;
  }
  const key = String(idempotencyKey || "").trim();
  if (key) body.idempotency_key = key.slice(0, 160);
  if (assistMeta) {
    const am: Record<string, unknown> = {
      kind: assistMeta.kind,
      mode: String(assistMeta.mode || "").slice(0, 64),
      source: String(assistMeta.source || "").slice(0, 32),
    };
    if (assistMeta.variant != null) am.variant = String(assistMeta.variant).slice(0, 32);
    if (assistMeta.brain_mode != null) am.brain_mode = String(assistMeta.brain_mode).slice(0, 64);
    if (assistMeta.was_recommended != null) am.was_recommended = Boolean(assistMeta.was_recommended);
    if (assistMeta.conversation_stage != null) am.conversation_stage = String(assistMeta.conversation_stage).slice(0, 64);
    if (assistMeta.conversation_mode != null) am.conversation_mode = String(assistMeta.conversation_mode).slice(0, 64);
    if (assistMeta.edited_after_insert != null) am.edited_after_insert = Boolean(assistMeta.edited_after_insert);
    body.assist_meta = am;
  }
  return body;
}

export async function sendThreadMessage(
  partnerUserId: number,
  content: string,
  conversationContext: string[],
  replyToMessageId?: string | null,
  voice?: VoiceAttachment | null,
  idempotencyKey?: string | null,
  assistMeta?: MessageAssistMeta | null,
): Promise<ChatSendResult> {
  // In-flight dedupe: prevents rapid double-click/Enter spam from issuing multiple identical POSTs.
  const inflightKey = `${Math.trunc(Number(partnerUserId))}:${String(idempotencyKey || "").trim()}`;
  if (idempotencyKey) {
    (sendThreadMessage as any)._inflight ||= new Map<string, Promise<ChatSendResult>>();
    const m = (sendThreadMessage as any)._inflight as Map<string, Promise<ChatSendResult>>;
    const existing = m.get(inflightKey);
    if (existing) return existing;
    const p = (async () => {
      try {
        const body = buildMessageCreatePayload(partnerUserId, content, conversationContext, replyToMessageId, voice, idempotencyKey, assistMeta);
        debugChat("send message POST body", body);

        const raw = await apiFetch("/messages", {
          method: "POST",
          metaReason: "chat-thread-send",
          body: JSON.stringify(body),
        });

        const normalized = normalizeSendMessageResponse(raw);
        if (!normalized) {
          throw new Error("The server returned an unexpected message payload.");
        }

        invalidateChatSummaryCaches();
        invalidateChatThreadCache(body.receiver_id);
        emitChatSync({ type: "messageSent", partnerUserId: body.receiver_id });
        return normalized;
      } finally {
        m.delete(inflightKey);
      }
    })();
    m.set(inflightKey, p);
    return p;
  }
  const body = buildMessageCreatePayload(partnerUserId, content, conversationContext, replyToMessageId, voice, idempotencyKey, assistMeta);
  debugChat("send message POST body", body);

  const raw = await apiFetch("/messages", {
    method: "POST",
    metaReason: "chat-thread-send",
    body: JSON.stringify(body),
  });

  const normalized = normalizeSendMessageResponse(raw);
  if (!normalized) {
    throw new Error("The server returned an unexpected message payload.");
  }

  invalidateChatSummaryCaches();
  invalidateChatThreadCache(body.receiver_id);
  emitChatSync({ type: "messageSent", partnerUserId: body.receiver_id });
  return normalized;
}

export async function reactToMessage(messageId: number, emoji: "❤️" | "👍" | "😂"): Promise<"added" | "removed"> {
  const raw = await apiFetch(`/messages/${messageId}/reactions`, {
    method: "POST",
    metaReason: "chat-react",
    body: JSON.stringify({ emoji }),
    skipThrottle: true,
  });
  const status = (raw && typeof raw === "object" ? (raw as any).status : "") as string;
  return status === "removed" ? "removed" : "added";
}

export type AiOpenerStyle =
  | "default"
  | "playful"
  | "confident"
  | "warm"
  | "flirty"
  | "witty"
  | "charming"
  | "direct"
  | "thoughtful"
  | "tease_lightly";

export async function fetchAiOpeners(
  targetUserId: number,
  options: { conversationContext?: string[]; languageHint?: string; style?: AiOpenerStyle; aiCtx?: AiLanguageToneContext } = {},
): Promise<string[]> {
  try {
    const { locale: aiLoc, language_hint: defaultHint } = getAiLocalePayload();
    const requestedLocale = normalizeAiLocaleTag(options.aiCtx?.overrideLanguage || options.aiCtx?.uiLocale || aiLoc);
    const raw = await apiFetch(`/ai/openers/${targetUserId}`, {
      method: "POST",
      metaReason: "ai-chat-openers",
      body: JSON.stringify({
        conversation_context: options.conversationContext ?? [],
        locale: requestedLocale,
        ai_locale: resolveAiLocaleOverride(options.aiCtx),
        language_hint: options.languageHint ?? defaultHint,
        style: options.style ?? "default",
      }),
      skipThrottle: true,
    });
    logAiData("ai/openers/{targetUserId}", raw);
    const rows = raw && typeof raw === "object" ? ((raw as any).openers as any) : null;
    if (!Array.isArray(rows)) return [];
    return rows
      .map((x) => (x && typeof x === "object" ? String((x as any).text || "") : String(x || "")))
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 3);
  } catch (error) {
    logAiGate("ai/openers/{targetUserId}", {
      targetUserId,
      style: options.style ?? "default",
      error: error instanceof Error ? error.message : String(error),
    });
    return [];
  }
}

export type AiOpenerMatchContext = {
  matchName: string;
  bio?: string | null;
  interests?: string[] | null;
  city?: string | null;
  tags?: string[] | null;
};

export type AiOpenerItem = { type: "safe" | "flirty" | "smart"; text: string };

function openerStyleForV1(style: AiOpenerStyle | undefined): string | null {
  if (!style || style === "default") return "playful";
  if (style === "playful") return "playful";
  if (style === "confident") return "confident";
  // Backend normalizes styles; "curious" is the closest to "warm".
  if (style === "warm") return "curious";
  if (style === "flirty") return "flirty";
  if (style === "witty") return "witty";
  if (style === "charming") return "charming";
  if (style === "direct") return "direct";
  if (style === "thoughtful") return "thoughtful";
  if (style === "tease_lightly") return "tease_lightly";
  return "playful";
}

/**
 * New v1 endpoint for opener suggestions.
 * Silent-fail contract: errors return [] so UI can hide without crashing.
 */
export type AiOpenersResult = { items: AiOpenerItem[]; suggestions: string[]; bestIndex: number };

const SESSION_OPENERS_CACHE_PREFIX = "neyra:ai_openers:v1:";

/** Clear in-memory opener cache (call when UI language changes; storage keys cleared separately). */
export function clearAiOpenersMemoryCache() {
  clearOpenerSessionMemoryCache();
}

function openerCacheKey(input: {
  threadId: number | string;
  matchName: string;
  uiLocale: string;
  aiLocale: string;
  style: string | null;
}): string {
  const tid = String(input.threadId);
  const nm = input.matchName.trim().toLowerCase();
  const uiLoc = String(input.uiLocale || "en").trim();
  const aiLoc = String(input.aiLocale || "en").trim();
  const st = String(input.style || "").trim().toLowerCase();
  return `${SESSION_OPENERS_CACHE_PREFIX}${tid}:${uiLoc}:${aiLoc}:${st}:${nm}`;
}

export async function getAiOpeners(
  threadId: number | string,
  matchContext: AiOpenerMatchContext,
  options: { style?: AiOpenerStyle; conversationContext?: string[]; aiCtx?: AiLanguageToneContext } = {},
): Promise<AiOpenersResult> {
  const match_name = String(matchContext?.matchName ?? "").trim();
  if (!match_name) return { items: [], suggestions: [], bestIndex: 0 };
  const bio = String(matchContext?.bio ?? "").trim();
  const city = String(matchContext?.city ?? "").trim();
  const interests = Array.isArray(matchContext?.interests)
    ? matchContext.interests.map((x) => String(x ?? "").trim()).filter(Boolean).slice(0, 12)
    : [];
  const tags = Array.isArray(matchContext?.tags)
    ? matchContext.tags.map((x) => String(x ?? "").trim()).filter(Boolean).slice(0, 24)
    : [];
  try {
    const uiLocale = (options.aiCtx?.uiLocale ?? getCurrentUiLocale() ?? getUiLocaleForAiRequests()) as string;
    const aiLocale = normalizeAiLocaleTag(options.aiCtx?.overrideLanguage || uiLocale);
    if (typeof window !== "undefined" && process.env.NODE_ENV !== "production") {
      console.info("[neyra-ai-locale]", { endpoint: "/ai/opener", locale: uiLocale });
    }
    const styleKey = openerStyleForV1(options.style);
    const ck = openerCacheKey({ threadId, matchName: match_name, uiLocale, aiLocale, style: styleKey });
    const memHit = openerSessionMem.get(ck) as AiOpenersResult | undefined;
    if (memHit) return memHit;
    try {
      const rawCached = sessionStorage.getItem(ck);
      if (rawCached) {
        const parsed = JSON.parse(rawCached) as AiOpenersResult | null;
        if (parsed && Array.isArray(parsed.suggestions) && Array.isArray(parsed.items)) {
          openerSessionMem.set(ck, parsed as unknown);
          return parsed;
        }
      }
    } catch {
      // ignore
    }
    const localeAtStart = String(uiLocale || "en");
    const { language_hint } = getAiLocalePayload();
    const raw = await apiFetch("/ai/opener", {
      method: "POST",
      metaReason: `ai-opener-v1:${String(threadId)}`,
      body: JSON.stringify({
        match_name,
        bio,
        interests,
        city,
        tags,
        conversation_context: options.conversationContext ?? [],
        style: styleKey,
        locale: aiLocale,
        ai_locale: resolveAiLocaleOverride(options.aiCtx),
        language_hint,
      }),
      skipThrottle: true,
    });
    // Ignore stale responses if locale changed mid-flight.
    if (String(getCurrentUiLocale()) !== localeAtStart) return { items: [], suggestions: [], bestIndex: 0 };
    logAiData("ai/opener", raw);
    if (normalizeAiLocaleTag((raw as any)?.locale ?? aiLocale) !== aiLocale) {
      throw new Error("ai_locale_mismatch");
    }
    const rows = raw && typeof raw === "object" ? ((raw as any).suggestions as any) : null;
    const itemRows = raw && typeof raw === "object" ? ((raw as any).items as any) : null;
    let bestIndex = 1;
    if (raw && typeof raw === "object") {
      const ri = Number((raw as any).recommended_index ?? (raw as any).recommendedIndex);
      if (Number.isFinite(ri)) bestIndex = Math.max(0, Math.min(2, Math.trunc(ri)));
    }
    if (!Array.isArray(rows)) return { items: [], suggestions: [], bestIndex: 0 };
    const suggestions = rows
      .map((x) => String(x ?? "").trim())
      .filter(Boolean)
      .slice(0, 3);
    bestIndex = Math.max(0, Math.min(suggestions.length - 1, bestIndex));
    let items: AiOpenerItem[] = [];
    if (Array.isArray(itemRows) && itemRows.length > 0) {
      items = itemRows
        .map((row: any) => {
          const typ = String(row?.type ?? "").toLowerCase();
          const text = String(row?.text ?? "").trim();
          if (typ !== "safe" && typ !== "flirty" && typ !== "smart") return null;
          if (!text) return null;
          return { type: typ as AiOpenerItem["type"], text };
        })
        .filter(Boolean) as AiOpenerItem[];
    }
    if (items.length < 3) {
      const order: AiOpenerItem["type"][] = ["safe", "flirty", "smart"];
      items = order.map((type, i) => ({
        type,
        text: suggestions[i] ?? "",
      }));
    }
    const out = { items: items.slice(0, 3), suggestions, bestIndex };
    openerSessionMem.set(ck, out as unknown);
    try {
      sessionStorage.setItem(ck, JSON.stringify(out));
    } catch {
      // ignore
    }
    return out;
  } catch (error) {
    logAiGate("ai/opener", {
      threadId,
      match_name,
      style: openerStyleForV1(options.style),
      error: error instanceof Error ? error.message : String(error),
    });
    return { items: [], suggestions: [], bestIndex: 0 };
  }
}

export type AiRewriteMode =
  | "polish"
  | "natural"
  | "shorter"
  | "flirtier"
  | "flirty"
  | "witty"
  | "charming"
  | "direct"
  | "thoughtful"
  | "tease_lightly"
  | "confident"
  | "softer"
  | "romantic"
  | "deep"
  | "playful";

export async function fetchAiRewriteVariants(
  draft: string,
  options: { conversationContext?: string[]; mode?: AiRewriteMode; aiCtx?: AiLanguageToneContext } = {},
): Promise<string[]> {
  const trimmed = (draft ?? "").trim();
  if (!trimmed) return [];
  try {
    const { locale: aiLoc, language_hint } = getAiLocalePayload();
    const requestedLocale = normalizeAiLocaleTag(options.aiCtx?.overrideLanguage || options.aiCtx?.uiLocale || aiLoc);
    const raw = await apiFetch("/ai/improve-reply", {
      method: "POST",
      metaReason: "ai-chat-rewrite",
      body: JSON.stringify({
        draft: trimmed,
        conversation_context: options.conversationContext ?? [],
        user_style: "chill",
        mode: options.mode ?? "polish",
        locale: requestedLocale,
        ai_locale: resolveAiLocaleOverride(options.aiCtx),
        language_hint,
      }),
      skipThrottle: true,
    });
    logAiData("ai/improve-reply", raw);
    const rows = raw && typeof raw === "object" ? ((raw as any).variants as any) : null;
    if (!Array.isArray(rows)) return [];
    return rows
      .map((x) => (x && typeof x === "object" ? String((x as any).text || "") : String(x || "")))
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 3);
  } catch (error) {
    logAiGate("ai/improve-reply", {
      mode: options.mode ?? "polish",
      error: error instanceof Error ? error.message : String(error),
    });
    return [];
  }
}

/**
 * v1 rewrite endpoint (quota + premium gating lives here).
 * Silent-fail contract: errors return [] so UI can stay subtle and never wipe draft.
 */
export async function getAiRewriteVariants(
  threadId: number | string,
  draft: string,
  options: { conversationContext?: string[]; mode?: AiRewriteMode; aiCtx?: AiLanguageToneContext } = {},
): Promise<string[]> {
  const trimmed = (draft ?? "").trim();
  if (!trimmed) return [];
  try {
    const { locale: defaultAiLocale, language_hint } = getAiLocalePayload();
    const uiLocale = (options.aiCtx?.uiLocale ?? defaultAiLocale) as string;
    const aiLocale = normalizeAiLocaleTag(options.aiCtx?.overrideLanguage || uiLocale);
    // Canonical rewrite endpoint: /ai/rewrite → { options: string[3] }
    try {
      const raw = await apiFetch("/ai/rewrite", {
        method: "POST",
        metaReason: `ai-rewrite:${String(threadId)}:${options.mode ?? "polish"}`,
        body: JSON.stringify({
          draft: trimmed,
          conversation_context: options.conversationContext ?? [],
          user_style: "chill",
          mode: options.mode ?? "polish",
          locale: aiLocale,
          ai_locale: resolveAiLocaleOverride(options.aiCtx),
          language_hint,
        }),
        skipThrottle: true,
      });
      logAiData("ai/rewrite", raw);
      const rows = raw && typeof raw === "object" ? ((raw as any).options as any) : null;
      if (normalizeAiLocaleTag((raw as any)?.locale ?? aiLocale) !== aiLocale) {
        throw new Error("ai_locale_mismatch");
      }
      if (Array.isArray(rows)) {
        return rows.map((x) => String(x || "").trim()).filter(Boolean).slice(0, 3);
      }
    } catch {
      // Back-compat fallback.
    }
    const legacy = await apiFetch("/ai/improve-reply", {
      method: "POST",
      metaReason: `ai-rewrite-v1:${String(threadId)}:${options.mode ?? "polish"}`,
      body: JSON.stringify({
        draft: trimmed,
        conversation_context: options.conversationContext ?? [],
        user_style: "chill",
        mode: options.mode ?? "polish",
        locale: aiLocale,
        ai_locale: resolveAiLocaleOverride(options.aiCtx),
        language_hint,
      }),
      skipThrottle: true,
    });
    logAiData("ai/improve-reply", legacy);
    if (normalizeAiLocaleTag((legacy as any)?.locale ?? aiLocale) !== aiLocale) {
      throw new Error("ai_locale_mismatch");
    }
    const rows = legacy && typeof legacy === "object" ? ((legacy as any).variants as any) : null;
    if (!Array.isArray(rows)) return [];
    return rows
      .map((x) => (x && typeof x === "object" ? String((x as any).text || "") : String(x || "")))
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 3);
  } catch (error) {
    logAiGate("ai/improve-reply", {
      threadId,
      mode: options.mode ?? "polish",
      error: error instanceof Error ? error.message : String(error),
    });
    return [];
  }
}

export async function syncUnreadStateForOpenedThread(partnerUserId: number): Promise<void> {
  const existing = syncUnreadInFlight.get(partnerUserId);
  if (existing) return existing;

  const job = (async () => {
    optimisticOpenThreadNavBadges(partnerUserId);
    dismissMatchesNewBadgeForPartner(partnerUserId);
    invalidateChatSummaryCaches();

    try {
      await postMatchesMarkSeen();
      debugChat("mark-seen success", {
        partnerUserId,
        badges: getNavBadgesSnapshot(),
      });
    } catch (error) {
      debugChat("mark-seen failed", { partnerUserId, error });
      // Non-fatal: the thread GET already updated read state server-side.
    } finally {
      invalidateChatSummaryCaches();
      emitChatSync({ type: "threadOpened", partnerUserId });
    }
  })().finally(() => {
    syncUnreadInFlight.delete(partnerUserId);
  });

  syncUnreadInFlight.set(partnerUserId, job);
  return job;
}

export function isNonFatalPollError(error: unknown): boolean {
  return (
    isRequestAborted(error) ||
    error instanceof ApiThrottleSkipError ||
    (error instanceof Error && error.name === "RateLimitError")
  );
}

export type ReadinessRole = "me" | "them";
export type ReadinessScoreBucket = "low" | "medium" | "high";

export type ReadinessScoreResult = {
  score: number;
  level: ReadinessScoreBucket;
  insight: string;
  tips: string[];
};

export async function fetchReadinessScore(options: {
  messages: { role: ReadinessRole; text: string }[];
  draft?: string | null;
  planTier: "free" | "premium" | "premium_plus";
}): Promise<ReadinessScoreResult | null> {
  try {
    const { locale: aiLoc, language_hint } = getAiLocalePayload();
    const uiLocale = getCurrentUiLocale() || aiLoc || "en";
    const raw = await apiFetch("/ai/readiness-score", {
      method: "POST",
      metaReason: "ai-readiness-score",
      softFail: true,
      body: JSON.stringify({
        messages: (options.messages || []).map((m) => ({ role: m.role, text: m.text })),
        draft: options.draft ?? null,
        plan_tier: options.planTier,
        locale: uiLocale,
        language_hint,
      }),
      skipThrottle: true,
    });
    if (typeof process !== "undefined" && process.env.NODE_ENV === "development")
      console.info("[chat-ai-locale]", { endpoint: "/ai/readiness-score", uiLocale, responseLocale: uiLocale });
    logAiData("ai/readiness-score", raw);
    if (raw === undefined || raw === null || typeof raw !== "object") return null;
    const score = Number((raw as any).score ?? 0);
    const level = String((raw as any).level ?? "medium") as ReadinessScoreBucket;
    const insight = String((raw as any).insight ?? "");
    const tipsRaw = (raw as any).tips;
    const tips = Array.isArray(tipsRaw) ? tipsRaw.map((x: any) => String(x ?? "").trim()).filter(Boolean).slice(0, 2) : [];
    return {
      score: Number.isFinite(score) ? Math.max(0, Math.min(100, Math.round(score))) : 0,
      level: level === "low" || level === "high" ? level : "medium",
      insight: insight.trim().slice(0, 180),
      tips,
    };
  } catch (error) {
    logAiGate("ai/readiness-score", {
      planTier: options.planTier,
      messageCount: options.messages.length,
      hasDraft: Boolean(options.draft?.trim()),
      error: error instanceof Error ? error.message : String(error),
    });
    return null;
  }
}

export type CoachState = "idle" | "nudge" | "opportunity" | "caution";
export type CoachActionType = "rewrite" | "opener" | "ask_question" | "voice_step" | "date_step";
export type CoachAction = { type: CoachActionType; label: string };
export type CoachResult = { state: CoachState; message: string; actions: CoachAction[] };
export type ConversationHealth = {
  health_score?: number | null;
  attraction_level?: "low" | "medium" | "high" | null;
  drop_risk?: "low" | "medium" | "high" | null;
  trend?: "improving" | "stable" | "declining" | null;
  signals?: string[];
  diagnosis?: string | null;
  next_move?: string | null;
  next_suggestions?: string[];
};

export async function fetchAiCoach(options: {
  messages: { role: ReadinessRole; text: string }[];
  draft: string | null;
  readinessScore: number | null;
}): Promise<(CoachResult & ConversationHealth) | null> {
  try {
    const { locale: aiLoc, language_hint } = getAiLocalePayload();
    const uiLocale = getCurrentUiLocale() || aiLoc || "en";
    const raw = await apiFetch("/ai/coach", {
      method: "POST",
      metaReason: "ai-coach",
      softFail: true,
      body: JSON.stringify({
        messages: (options.messages || []).map((m) => ({ role: m.role, text: m.text })),
        draft: options.draft ?? null,
        readiness_score: options.readinessScore ?? null,
        locale: uiLocale,
        language_hint,
      }),
      skipThrottle: true,
    });
    if (typeof process !== "undefined" && process.env.NODE_ENV === "development")
      console.info("[chat-ai-locale]", { endpoint: "/ai/coach", uiLocale, responseLocale: uiLocale });
    logAiData("ai/coach", raw);
    if (raw === undefined || raw === null || typeof raw !== "object") return null;
    const state = String((raw as any).state ?? "idle") as CoachState;
    const message = String((raw as any).message ?? "").trim();
    const actionsRaw = (raw as any).actions;
    const actions = Array.isArray(actionsRaw)
      ? actionsRaw
          .map((a: any) => ({
            type: String(a?.type ?? "") as CoachActionType,
            label: String(a?.label ?? "").trim(),
          }))
          .filter((a: CoachAction) => Boolean(a.type) && Boolean(a.label))
          .slice(0, 2)
      : [];
    const normalized: CoachResult & ConversationHealth = {
      state: state === "nudge" || state === "opportunity" || state === "caution" ? state : "idle",
      message: message.slice(0, 200),
      actions,
      health_score: Number.isFinite((raw as any).health_score) ? Number((raw as any).health_score) : null,
      attraction_level: (["low", "medium", "high"].includes(String((raw as any).attraction_level || "")) ? String((raw as any).attraction_level) : null) as any,
      drop_risk: (["low", "medium", "high"].includes(String((raw as any).drop_risk || "")) ? String((raw as any).drop_risk) : null) as any,
      trend: (["improving", "stable", "declining"].includes(String((raw as any).trend || "")) ? String((raw as any).trend) : null) as any,
      signals: Array.isArray((raw as any).signals) ? (raw as any).signals.map((x: any) => String(x || "").trim()).filter(Boolean).slice(0, 10) : [],
      diagnosis: typeof (raw as any).diagnosis === "string" ? String((raw as any).diagnosis).trim() : null,
      next_move: typeof (raw as any).next_move === "string" ? String((raw as any).next_move).trim() : null,
      next_suggestions: Array.isArray((raw as any).next_suggestions) ? (raw as any).next_suggestions.map((x: any) => String(x || "").trim()).filter(Boolean).slice(0, 3) : [],
    };
    return normalized;
  } catch (error) {
    logAiGate("ai/coach", {
      messageCount: options.messages.length,
      hasDraft: Boolean(options.draft?.trim()),
      readinessScore: options.readinessScore,
      error: error instanceof Error ? error.message : String(error),
    });
    return null;
  }
}

export type EscalationPrimaryStep = "none" | "voice" | "video" | "date";
export type EscalationReadinessResult = {
  voice_ready: boolean;
  video_ready: boolean;
  date_ready: boolean;
  primary_step: EscalationPrimaryStep;
  confidence: number;
  message: string;
};

export async function fetchEscalationReadiness(options: {
  messages: { role: ReadinessRole; text: string }[];
  readinessScore: number | null;
  coachState: CoachState | null;
}): Promise<EscalationReadinessResult | null> {
  try {
    const raw = await apiFetch("/ai/escalation-readiness", {
      method: "POST",
      metaReason: "ai-escalation-readiness",
      body: JSON.stringify({
        messages: (options.messages || []).map((m) => ({ role: m.role, text: m.text })),
        readiness_score: options.readinessScore ?? null,
        coach_state: options.coachState ?? null,
        locale: getStoredLocale(),
      }),
      skipThrottle: true,
    });
    logAiData("ai/escalation-readiness", raw);
    if (!raw || typeof raw !== "object") return null;
    const primaryRaw = String((raw as any).primary_step ?? "none") as EscalationPrimaryStep;
    const primary: EscalationPrimaryStep =
      primaryRaw === "voice" || primaryRaw === "video" || primaryRaw === "date" ? primaryRaw : "none";
    const confidence = Number((raw as any).confidence ?? 0);
    const message = String((raw as any).message ?? "").trim();
    return {
      voice_ready: Boolean((raw as any).voice_ready),
      video_ready: Boolean((raw as any).video_ready),
      date_ready: Boolean((raw as any).date_ready),
      primary_step: primary,
      confidence: Number.isFinite(confidence) ? Math.max(0, Math.min(100, Math.round(confidence))) : 0,
      message: message.slice(0, 200),
    };
  } catch (error) {
    logAiGate("ai/escalation-readiness", {
      messageCount: options.messages.length,
      readinessScore: options.readinessScore,
      coachState: options.coachState,
      error: error instanceof Error ? error.message : String(error),
    });
    return null;
  }
}

export async function fetchEscalationDrafts(options: {
  kind: "voice" | "video" | "date";
  matchName?: string | null;
  interests?: string[] | null;
}): Promise<string[] | null> {
  try {
    const raw = await apiFetch("/ai/escalation-drafts", {
      method: "POST",
      metaReason: "ai-escalation-drafts",
      body: JSON.stringify({
        kind: options.kind,
        match_name: options.matchName ?? "",
        interests: Array.isArray(options.interests) ? options.interests.slice(0, 6) : [],
        locale: getStoredLocale(),
      }),
      skipThrottle: true,
    });
    logAiData("ai/escalation-drafts", raw);
    if (!raw || typeof raw !== "object") return null;
    const draftsRaw = (raw as any).drafts;
    const drafts = Array.isArray(draftsRaw)
      ? draftsRaw.map((x: any) => String(x ?? "").trim()).filter(Boolean).slice(0, 3)
      : [];
    return drafts.length ? drafts : null;
  } catch (error) {
    logAiGate("ai/escalation-drafts", {
      kind: options.kind,
      error: error instanceof Error ? error.message : String(error),
    });
    return null;
  }
}

export type RecoveryState = "idle" | "soft_nudge" | "revive" | "let_it_breathe";
export type RecoveryResult = { state: RecoveryState; message: string; suggestions: string[] };

export async function fetchAiRecovery(options: {
  messages: { role: ReadinessRole; text: string }[];
  lastMessageAgeMinutes: number | null;
  readinessScore: number | null;
  coachState: CoachState | null;
}): Promise<RecoveryResult | null> {
  try {
    const raw = await apiFetch("/ai/recovery", {
      method: "POST",
      metaReason: "ai-recovery",
      body: JSON.stringify({
        messages: (options.messages || []).map((m) => ({ role: m.role, text: m.text })),
        last_message_age_minutes: options.lastMessageAgeMinutes ?? null,
        readiness_score: options.readinessScore ?? null,
        coach_state: options.coachState ?? null,
        locale: getStoredLocale(),
      }),
      skipThrottle: true,
    });
    logAiData("ai/recovery", raw);
    if (!raw || typeof raw !== "object") return null;
    const stateRaw = String((raw as any).state ?? "idle") as RecoveryState;
    const state: RecoveryState =
      stateRaw === "soft_nudge" || stateRaw === "revive" || stateRaw === "let_it_breathe" ? stateRaw : "idle";
    const message = String((raw as any).message ?? "").trim();
    const suggestionsRaw = (raw as any).suggestions;
    const suggestions = Array.isArray(suggestionsRaw)
      ? suggestionsRaw.map((x: any) => String(x ?? "").trim()).filter(Boolean).slice(0, 3)
      : [];
    return { state, message: message.slice(0, 200), suggestions };
  } catch (error) {
    logAiGate("ai/recovery", {
      messageCount: options.messages.length,
      lastMessageAgeMinutes: options.lastMessageAgeMinutes,
      readinessScore: options.readinessScore,
      coachState: options.coachState,
      error: error instanceof Error ? error.message : String(error),
    });
    return null;
  }
}
