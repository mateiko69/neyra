"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage } from "../../../lib/chat/types";
import { conversationContext } from "../../../lib/chat/normalize";
import { fetchAiReplyOptions } from "../../../lib/chat/api";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { useT } from "../../components/i18n/I18nProvider";
import { neyraChatSuggestionDevLog } from "../../../lib/chat/neyraAiLocaleLog";
import { Button } from "./../ui";

type Props = {
  viewerUserId: number | null;
  partnerUserId: number | null;
  messages: ChatMessage[];
  draft: string;
  disabled?: boolean;
  aiCtx?: import("../../../lib/chat/api").AiLanguageToneContext;
  onInsertDraft: (text: string, meta: { optionIndex: number; optionText: string }) => void;
  onSendNow: (text: string, meta: { optionIndex: number; optionText: string }) => void | Promise<void>;
};

function prefKey(viewerUserId: number) {
  return `ai:reply_style_pref:${viewerUserId}`;
}

type ReplyOptionKey = "light" | "flirty" | "deep";
type ReplyOption = {
  key: ReplyOptionKey;
  label: string;
  text: string;
  why: string[];
  optionIndex: 0 | 1 | 2;
};

const replyCache = new Map<string, { options: ReplyOption[]; bestIndex: number; at: number }>();

function stableSeed(): string {
  const n = Math.trunc(Math.random() * 1_000_000_000);
  return String(n);
}

function computeStage(messages: ChatMessage[]): "early" | "mid" | "late" {
  const n = Array.isArray(messages) ? messages.length : 0;
  if (n < 6) return "early";
  if (n < 18) return "mid";
  return "late";
}

function bestIndexForStage(stage: "early" | "mid" | "late"): 0 | 1 | 2 {
  if (stage === "early") return 0;
  if (stage === "mid") return 1;
  return 2;
}

export function ChatAiReplyOptionsInline({ viewerUserId, partnerUserId, messages, draft, disabled = false, aiCtx, onInsertDraft, onSendNow }: Props) {
  const { t } = useT("ChatAiReplyOptionsInline");
  const [loading, setLoading] = useState(false);
  const [options, setOptions] = useState<ReplyOption[]>([]);
  const [bestIndex, setBestIndex] = useState<number>(-1);
  const [quotaMessage, setQuotaMessage] = useState<string>("");
  const lastIncomingIdRef = useRef<string>("");
  const lastGenRef = useRef(0);
  const insertedAtRef = useRef<{ at: number; text: string; idx: number } | null>(null);
  const ctx = useMemo(() => conversationContext(messages, 10), [messages]);

  const lastIncoming = useMemo(() => {
    if (!partnerUserId) return null;
    const last = (messages || []).slice(-1)[0] ?? null;
    if (!last) return null;
    if (last.senderId !== partnerUserId) return null;
    return last;
  }, [messages, partnerUserId]);

  useEffect(() => {
    // Track "edited after insert" (simple heuristic).
    const ins = insertedAtRef.current;
    if (!ins) return;
    if (!draft.trim()) return;
    if (draft.trim() === ins.text.trim()) return;
    // Only count once.
    insertedAtRef.current = null;
    void trackAnalyticsEvent("user_selected_option_edited", { option_index: ins.idx });
  }, [draft]);

  const onGenerate = async (reason: "auto" | "more" | "manual") => {
    if (disabled) return;
    if (!viewerUserId || !partnerUserId) return;
    if (!lastIncoming) return;
    const incomingId = String(lastIncoming.rawId ?? lastIncoming.id ?? lastIncoming.createdAt ?? "");
    if (!incomingId) return;
    lastIncomingIdRef.current = incomingId;

    const lastText = String((lastIncoming as any).content ?? "").trim();
    if (!lastText) return;

    const preferredStyle =
      typeof window !== "undefined"
        ? (localStorage.getItem(prefKey(viewerUserId)) || "").trim()
        : "";

    const stage = computeStage(messages);
    const cacheKey = `${String(viewerUserId)}:${String(partnerUserId)}:${incomingId}:${String(aiCtx?.uiLocale || "")}:${stage}`;
    if (reason !== "more") {
      const cached = replyCache.get(cacheKey);
      if (cached && Date.now() - cached.at < 2 * 60_000) {
        setOptions(cached.options);
        setBestIndex(cached.bestIndex);
        return;
      }
    }

    const gen = (lastGenRef.current += 1);
    setQuotaMessage("");
    setLoading(true);
    setOptions([]);
    setBestIndex(-1);
    void trackAnalyticsEvent("ai_request_started", { surface: "chat_inline_replies" });

    try {
      const out = await fetchAiReplyOptions({
        lastMessage: lastText,
        conversationContext: [...ctx, `VARIATION_SEED:${stableSeed()}`, `STAGE:${stage}`].slice(-10),
        userPreferredStyle: preferredStyle || null,
        aiCtx,
      });
      if (lastGenRef.current !== gen) return;
      const best = bestIndexForStage(stage);
      const pack: ReplyOption[] = [
        {
          key: "light" as const,
          label: t("chat.ai.inlineReplies.style.light"),
          text: String(out?.[0] || "").trim(),
          why: [t("chat.ai.inlineReplies.why.flow"), t("chat.ai.inlineReplies.why.light")],
          optionIndex: 0 as const,
        },
        {
          key: "flirty" as const,
          label: t("chat.ai.inlineReplies.style.flirty"),
          text: String(out?.[1] || "").trim(),
          why: [t("chat.ai.inlineReplies.why.flow"), t("chat.ai.inlineReplies.why.flirty")],
          optionIndex: 1 as const,
        },
        {
          key: "deep" as const,
          label: t("chat.ai.inlineReplies.style.deep"),
          text: String(out?.[2] || "").trim(),
          why: [t("chat.ai.inlineReplies.why.flow"), t("chat.ai.inlineReplies.why.deep")],
          optionIndex: 2 as const,
        },
      ].filter((o) => Boolean(o.text));

      setOptions(pack);
      setBestIndex(Math.max(0, Math.min(pack.length - 1, best)));
      if (pack.length) replyCache.set(cacheKey, { options: pack, bestIndex: Math.max(0, Math.min(pack.length - 1, best)), at: Date.now() });
      neyraChatSuggestionDevLog({
        component: "ChatAiReplyOptionsInline",
        endpoint: "/api/v1/ai/reply-options",
        locale: String(aiCtx?.uiLocale || aiCtx?.overrideLanguage || "").trim() || "en",
        source: "reply-options",
        fallback: pack.length === 0,
        last_message_preview: lastText.slice(0, 220),
      });
      void trackAnalyticsEvent("ai_chat_suggestions_generated", {
        options_count: Math.min(3, out.length || 0),
        ai_provider: "gemini",
      });
    } catch (error) {
      if (lastGenRef.current !== gen) return;
      const msg = error instanceof Error ? error.message : String(error);
      if (msg.toLowerCase().includes("ai_quota_exhausted") || msg.toLowerCase().includes("quota") || msg.toLowerCase().includes("429") || msg.toLowerCase().includes("rate limit")) {
        setQuotaMessage(t("chat.ai.quota.dailyExhausted"));
        setOptions([]);
        return;
      }
      setOptions([]);
    } finally {
      if (lastGenRef.current === gen) setLoading(false);
    }
  };

  useEffect(() => {
    if (disabled) return;
    if (!viewerUserId || !partnerUserId) return;
    if (!lastIncoming) return;
    if (draft.trim()) return;
    const incomingId = String(lastIncoming.rawId ?? lastIncoming.id ?? lastIncoming.createdAt ?? "");
    if (!incomingId) return;
    if (incomingId === lastIncomingIdRef.current) return;
    void onGenerate("auto");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [disabled, viewerUserId, partnerUserId, lastIncoming?.id, lastIncoming?.rawId, lastIncoming?.createdAt]);

  if (!partnerUserId) return null;
  if (!lastIncoming) return null;
  if (quotaMessage) {
    return (
      <div className="chat-ai-replies">
        <div className="chat-ai-replies__label">{t("chat.ai.inlineReplies.title")}</div>
        <div style={{ padding: "10px 12px", borderRadius: 14, border: "1px solid rgba(255, 138, 91, 0.25)", background: "rgba(255, 138, 91, 0.08)" }}>
          {quotaMessage}
        </div>
        <button type="button" className="btn btn-ghost" onClick={() => void onGenerate("manual")} disabled={disabled || loading} style={{ marginTop: 10, justifySelf: "start" }}>
          {t("common.tryAgain")}
        </button>
      </div>
    );
  }
  if (loading) {
    return (
      <div className="chat-ai-replies">
        <div className="chat-ai-replies__label">{t("chat.ai.inlineReplies.title")}</div>
        <div className="chat-ai-replies__row">
          <div className="chat-ai-replies__skeleton" />
          <div className="chat-ai-replies__skeleton" />
          <div className="chat-ai-replies__skeleton" />
        </div>
      </div>
    );
  }

  if (!options.length) {
    return (
      <div className="chat-ai-replies">
        <div className="chat-ai-replies__label">{t("chat.ai.inlineReplies.title")}</div>
        <Button type="button" disabled={disabled || loading} onClick={() => void onGenerate("manual")}>
          {t("chat.ai.inlineReplies.moreIdeas")}
        </Button>
      </div>
    );
  }

  return (
    <div className="chat-ai-replies">
      <div className="chat-ai-replies__label">{t("chat.ai.inlineReplies.title")}</div>
      <div style={{ marginTop: 8, marginBottom: 8 }}>
        <Button type="button" variant="ghost" disabled={disabled || loading} onClick={() => void onGenerate("more")}>
          {t("chat.ai.inlineReplies.moreIdeas")}
        </Button>
      </div>
      <div className="chat-ai-replies__row">
        {options.slice(0, 3).map((opt, idx) => {
          const isBest = bestIndex === idx;
          return (
            <div key={`${opt.key}:${opt.text}`} className="chat-ai-replies__option" style={{ padding: 12, borderRadius: 14 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                <div className="text-purple-300" style={{ fontWeight: 900 }}>{opt.label}</div>
                {isBest ? <div className="chat-ai-inline__best-pill">🔥 {t("chat.ai.inlineReplies.bestReply")}</div> : null}
              </div>
              <div className="chat-ai-replies__text text-white/90" style={{ marginTop: 8 }}>
                {opt.text}
              </div>
              <div style={{ marginTop: 10, display: "flex", gap: 10, flexWrap: "wrap" }}>
                <Button
                  type="button"
                  disabled={disabled}
                  onClick={() => {
                    const cleaned = String(opt.text || "").trim();
                    if (!cleaned) return;
                    try {
                      if (viewerUserId) localStorage.setItem(prefKey(viewerUserId), opt.key);
                    } catch {
                      // ignore
                    }
                    void trackAnalyticsEvent("user_selected_option", { option_index: opt.optionIndex, delivery: "send" });
                    void trackAnalyticsEvent("ai_reply_option_sent_now", { option_index: opt.optionIndex });
                    void Promise.resolve(onSendNow(cleaned, { optionIndex: opt.optionIndex, optionText: cleaned }));
                  }}
                >
                  {t("chat.ai.suggestion.send")}
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={disabled}
                  onClick={() => {
                    const cleaned = String(opt.text || "").trim();
                    if (!cleaned) return;
                    insertedAtRef.current = { at: Date.now(), text: cleaned, idx: opt.optionIndex };
                    try {
                      if (viewerUserId) localStorage.setItem(prefKey(viewerUserId), opt.key);
                    } catch {
                      // ignore
                    }
                    void trackAnalyticsEvent("user_selected_option", { option_index: opt.optionIndex, delivery: "edit" });
                    onInsertDraft(cleaned, { optionIndex: opt.optionIndex, optionText: cleaned });
                  }}
                >
                  {t("chat.ai.suggestion.edit")}
                </Button>
              </div>
              <div style={{ marginTop: 10 }}>
                <div className="caption text-white/70" style={{ opacity: 0.9, fontWeight: 850 }}>
                  {t("chat.ai.inlineReplies.whyTitle")}
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
    </div>
  );
}

