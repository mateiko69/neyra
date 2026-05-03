"use client";

import { useMemo, useRef, useState } from "react";
import type { ChatMessage, ChatPartnerProfile } from "../../../lib/chat/types";
import { conversationContext } from "../../../lib/chat/normalize";
import { fetchAiOpeners, fetchAiRewriteVariants, type AiOpenerStyle, type AiRewriteMode } from "../../../lib/chat/api";
import {
  draftStateFromDraft,
  threadStateFromMessages,
  trackAiAssistRequested,
  trackAiAssistSuggestionSelected,
  type AiAssistMode,
} from "../../../lib/chat/aiAssistAnalytics";
import { useT } from "../i18n/I18nProvider";
import { Button, Skeleton } from "../ui";

type SuggestionKind = "openers" | "rewrite";

type Props = {
  partnerUserId: number;
  partner: ChatPartnerProfile | null;
  messages: ChatMessage[];
  draft: string;
  disabled?: boolean;
  open: boolean;
  onClose: () => void;
  onInsertDraft: (next: string, meta: { kind: SuggestionKind; suggestion: string }) => void;
};

const openerActions: { key: string; style: AiOpenerStyle }[] = [
  { key: "chat.aiAssist.openers.default", style: "default" },
  { key: "chat.aiAssist.openers.playful", style: "playful" },
  { key: "chat.aiAssist.openers.confident", style: "confident" },
  { key: "chat.aiAssist.openers.warm", style: "warm" },
];

const rewriteActions: { key: string; mode: AiRewriteMode }[] = [
  { key: "chat.aiAssist.rewrite.polish", mode: "polish" },
  { key: "chat.aiAssist.rewrite.shorter", mode: "shorter" },
  { key: "chat.aiAssist.rewrite.flirtier", mode: "flirtier" },
  { key: "chat.aiAssist.rewrite.natural", mode: "natural" },
];

export function ChatAiAssistPanel({
  partnerUserId,
  partner,
  messages,
  draft,
  disabled = false,
  open,
  onClose,
  onInsertDraft,
}: Props) {
  const { t } = useT("ChatAiAssistPanel");
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [activeKind, setActiveKind] = useState<SuggestionKind>("openers");
  const [lastActionKey, setLastActionKey] = useState<string>("");
  const lastRequestGenRef = useRef(0);

  const ctx = useMemo(() => conversationContext(messages, 12), [messages]);
  const hasDraft = Boolean((draft ?? "").trim());
  const showOpeners = !hasDraft;
  const showRewrite = hasDraft;

  async function runOpeners(style: AiOpenerStyle, actionKey: string) {
    if (disabled || loading) return;
    setActiveKind("openers");
    setLastActionKey(actionKey);
    setLoading(true);
    setSuggestions([]);
    const gen = (lastRequestGenRef.current += 1);
    try {
      const mode: AiAssistMode =
        style === "playful"
          ? "playful"
          : style === "confident"
            ? "confident"
            : style === "warm"
              ? "warm"
              : "suggest_opener";
      void trackAiAssistRequested({
        assist_type: "opener",
        mode,
        thread_state: threadStateFromMessages(messages.length),
        draft_state: draftStateFromDraft(draft),
        source: "inline_panel",
        plan_tier: "free",
      });
      const rows = await fetchAiOpeners(partnerUserId, {
        conversationContext: ctx,
        languageHint: null,
        style,
      });
      if (lastRequestGenRef.current !== gen) return;
      setSuggestions(rows.slice(0, 3));
    } finally {
      if (lastRequestGenRef.current === gen) setLoading(false);
    }
  }

  async function runRewrite(mode: AiRewriteMode, actionKey: string) {
    if (disabled || loading) return;
    const trimmed = (draft ?? "").trim();
    if (!trimmed) return;
    setActiveKind("rewrite");
    setLastActionKey(actionKey);
    setLoading(true);
    setSuggestions([]);
    const gen = (lastRequestGenRef.current += 1);
    try {
      const assistMode: AiAssistMode =
        mode === "natural" ? "more_natural" : mode === "shorter" ? "shorter" : "polish";
      void trackAiAssistRequested({
        assist_type: "rewrite",
        mode: assistMode,
        thread_state: threadStateFromMessages(messages.length),
        draft_state: draftStateFromDraft(draft),
        source: "inline_panel",
        plan_tier: "free",
      });
      const rows = await fetchAiRewriteVariants(trimmed, { conversationContext: ctx, mode });
      if (lastRequestGenRef.current !== gen) return;
      setSuggestions(rows.slice(0, 3));
    } finally {
      if (lastRequestGenRef.current === gen) setLoading(false);
    }
  }

  if (!open) return null;

  return (
    <div className="chat-ai">
      <div className="chat-ai__top">
        <div className="chat-ai__title">
          <span className="chat-ai__title-label">{t("chat.aiAssist.title")}</span>
          {partner?.displayName ? (
            <span className="chat-ai__title-muted">{t("chat.aiAssist.forPartner", { name: partner.displayName })}</span>
          ) : null}
        </div>
        <button type="button" className="chat-ai__close" onClick={onClose} aria-label={t("chat.aiAssist.closeAria")}>
          ×
        </button>
      </div>

      <div className="chat-ai__actions" role="group" aria-label={t("chat.aiAssist.actionsAria")}>
        {showOpeners
          ? openerActions.map((a) => (
              <button
                key={a.key}
                type="button"
                className="chat-ai__chip"
                onClick={() => void runOpeners(a.style, a.key)}
                disabled={disabled || loading}
              >
                {t(a.key)}
              </button>
            ))
          : null}
        {showRewrite
          ? rewriteActions.map((a) => (
              <button
                key={a.key}
                type="button"
                className="chat-ai__chip"
                onClick={() => void runRewrite(a.mode, a.key)}
                disabled={disabled || loading}
              >
                {t(a.key)}
              </button>
            ))
          : null}
      </div>

      <div className="chat-ai__results" aria-label={t("chat.aiAssist.suggestionsAria")}>
        {loading ? (
          <div className="chat-ai__skeleton">
            <Skeleton className="chat-ai__skeleton-row" />
            <Skeleton className="chat-ai__skeleton-row" />
            <Skeleton className="chat-ai__skeleton-row" />
          </div>
        ) : suggestions.length > 0 ? (
          <div className="chat-ai__suggestions">
            {suggestions.map((text, index) => (
              <button
                key={`${activeKind}:${index}:${text}`}
                type="button"
                className="chat-ai__suggestion"
                onClick={() => {
                  const mode: AiAssistMode =
                    activeKind === "rewrite"
                      ? lastActionKey === "chat.aiAssist.rewrite.natural"
                        ? "more_natural"
                        : lastActionKey === "chat.aiAssist.rewrite.shorter"
                          ? "shorter"
                          : "polish"
                      : lastActionKey === "chat.aiAssist.openers.playful"
                        ? "playful"
                        : lastActionKey === "chat.aiAssist.openers.confident"
                          ? "confident"
                          : lastActionKey === "chat.aiAssist.openers.warm"
                            ? "warm"
                            : "suggest_opener";
                  const suggestion_index = (index === 0 ? 0 : index === 1 ? 1 : 2) as 0 | 1 | 2;
                  void trackAiAssistSuggestionSelected({
                    assist_type: activeKind === "rewrite" ? "rewrite" : "opener",
                    mode,
                    thread_state: threadStateFromMessages(messages.length),
                    draft_state: draftStateFromDraft(draft),
                    source: "inline_panel",
                    plan_tier: "free",
                    suggestion_index,
                  });
                  onInsertDraft(text, { kind: activeKind, suggestion: text });
                }}
                disabled={disabled}
              >
                <div className="chat-ai__suggestion-text text-white/90">{text}</div>
              </button>
            ))}
          </div>
        ) : (
          <div className="chat-ai__empty">
            <div className="chat-ai__empty-title">
              {lastActionKey
                ? t("chat.aiAssist.empty.noSuggestions")
                : showOpeners
                  ? t("chat.aiAssist.empty.needOpener")
                  : t("chat.aiAssist.empty.wantRewrite")}
            </div>
            <div className="chat-ai__empty-sub">
              {lastActionKey
                ? t("chat.aiAssist.empty.tryLater")
                : showOpeners
                  ? t("chat.aiAssist.empty.hintOpeners")
                  : t("chat.aiAssist.empty.hintRewrite")}
            </div>
            <div className="chat-ai__empty-actions">
              {lastActionKey ? (
                <Button
                  type="button"
                  variant="ghost"
                  className="chat-ai__try"
                  onClick={() => {
                    // repeat last action based on which row group is visible
                    const opener = openerActions.find((x) => x.key === lastActionKey) ?? null;
                    const rewrite = rewriteActions.find((x) => x.key === lastActionKey) ?? null;
                    if (opener) void runOpeners(opener.style, opener.key);
                    else if (rewrite) void runRewrite(rewrite.mode, rewrite.key);
                  }}
                  disabled={disabled}
                >
                  {t("chat.aiAssist.tryAgain")}
                </Button>
              ) : null}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

