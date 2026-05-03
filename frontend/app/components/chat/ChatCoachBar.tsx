"use client";

import { useEffect } from "react";
import { useT } from "../i18n/I18nProvider";

export type CoachAction = { type: "rewrite" | "opener" | "ask_question" | "voice_step" | "date_step"; label: string };
export type CoachState = "idle" | "nudge" | "opportunity" | "caution";
export type CoachLevel = "safe" | "better" | "risky";

type Props = {
  state: CoachState;
  message: string;
  actions: CoachAction[];
  level?: CoachLevel;
  onHide?: () => void;
  onViewed: () => void;
  onDismiss: () => void;
  onAction: (action: CoachAction) => void;
  disabled?: boolean;
};

export function ChatCoachBar({ state, message, actions, level = "better", onHide, onViewed, onDismiss, onAction, disabled = false }: Props) {
  const show = state !== "idle" && Boolean(message.trim());
  const { t } = useT("ChatCoachBar");

  useEffect(() => {
    if (!show) return;
    onViewed();
  }, [onViewed, show]);

  if (!show) return null;

  const levelLabel = level === "safe" ? "🟢" : level === "risky" ? "🔴" : "🟡";

  return (
    <div className="chat-coach" aria-label={t("chat.ai.coach.aria")}>
      <div className="chat-coach__row">
        <div className="chat-coach__badge" aria-hidden>
          {levelLabel} AI
        </div>
        <div className="chat-coach__text">{message}</div>
        {onHide ? (
          <button type="button" className="chat-coach__close" onClick={onHide} disabled={disabled} aria-label={t("chat.ai.coach.hide")}>
            {t("chat.ai.coach.hide")}
          </button>
        ) : null}
        <button
          type="button"
          className="chat-coach__close"
          onClick={onDismiss}
          disabled={disabled}
          aria-label={t("chat.ai.coach.dismiss")}
        >
          ×
        </button>
      </div>
      {actions?.length ? (
        <div className="chat-coach__actions" role="group" aria-label={t("chat.ai.coach.actionsAria")}>
          {actions.slice(0, 2).map((a) => (
            <button
              key={`${a.type}:${a.label}`}
              type="button"
              className="chat-ai__chip chat-coach__chip"
              onClick={() => onAction(a)}
              disabled={disabled}
            >
              {a.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

