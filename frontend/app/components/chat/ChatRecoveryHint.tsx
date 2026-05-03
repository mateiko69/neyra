"use client";

import { useEffect } from "react";
import { useT } from "../i18n/I18nProvider";

export type RecoveryState = "soft_nudge" | "revive" | "let_it_breathe";

type Props = {
  state: RecoveryState;
  message: string;
  suggestions: string[];
  onViewed: () => void;
  onDismiss: () => void;
  onPickSuggestion: (text: string, index: number) => void;
  disabled?: boolean;
};

export function ChatRecoveryHint({
  state,
  message,
  suggestions,
  onViewed,
  onDismiss,
  onPickSuggestion,
  disabled = false,
}: Props) {
  const show = Boolean(message.trim()) && (state === "soft_nudge" || state === "revive" || state === "let_it_breathe");
  const { t } = useT("ChatRecoveryHint");

  useEffect(() => {
    if (!show) return;
    onViewed();
  }, [onViewed, show]);

  if (!show) return null;

  return (
    <div className="chat-recovery" aria-label={t("chat.ai.recovery.aria")}>
      <div className="chat-recovery__row">
        <div className="chat-recovery__badge" aria-hidden>
          AI
        </div>
        <div className="chat-recovery__text">{message}</div>
        <button
          type="button"
          className="chat-recovery__close"
          onClick={onDismiss}
          disabled={disabled}
          aria-label={t("chat.ai.recovery.dismiss")}
        >
          ×
        </button>
      </div>
      {suggestions?.length ? (
        <div className="chat-recovery__suggestions" role="group" aria-label={t("chat.ai.recovery.suggestionsAria")}>
          {suggestions.slice(0, 3).map((s, i) => (
            <button
              key={`${i}:${s}`}
              type="button"
              className="chat-ai__chip chat-recovery__chip"
              onClick={() => onPickSuggestion(s, i)}
              disabled={disabled}
            >
              {s}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

