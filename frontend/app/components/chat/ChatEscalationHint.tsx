"use client";

import { useEffect } from "react";
import { useT } from "../i18n/I18nProvider";

export type EscalationPrimaryStep = "voice" | "video" | "date";

type Props = {
  primaryStep: EscalationPrimaryStep;
  confidence: number;
  message: string;
  onViewed: () => void;
  onDismiss: () => void;
  onAction: (step: EscalationPrimaryStep) => void;
  disabled?: boolean;
};

export function ChatEscalationHint({
  primaryStep,
  confidence,
  message,
  onViewed,
  onDismiss,
  onAction,
  disabled = false,
}: Props) {
  const show = Boolean(message.trim());
  const { t } = useT("ChatEscalationHint");

  function chipLabel(step: EscalationPrimaryStep): string {
    if (step === "voice") return t("chat.ai.escalation.action.voice");
    if (step === "video") return t("chat.ai.escalation.action.video");
    return t("chat.ai.escalation.action.date");
  }

  useEffect(() => {
    if (!show) return;
    onViewed();
  }, [onViewed, show]);

  if (!show) return null;

  return (
    <div className="chat-escalation" aria-label={t("chat.ai.escalation.aria")}>
      <div className="chat-escalation__row">
        <div className="chat-escalation__badge" aria-hidden>
          AI
        </div>
        <div className="chat-escalation__text">
          {message}
          {confidence >= 80 ? <span className="chat-escalation__conf">{t("chat.ai.escalation.strong")}</span> : null}
        </div>
        <button
          type="button"
          className="chat-escalation__close"
          onClick={onDismiss}
          disabled={disabled}
          aria-label={t("chat.ai.escalation.dismiss")}
        >
          ×
        </button>
      </div>
      <div className="chat-escalation__actions" role="group" aria-label={t("chat.ai.escalation.actionsAria")}>
        <button
          type="button"
          className="chat-ai__chip chat-escalation__chip"
          onClick={() => onAction(primaryStep)}
          disabled={disabled}
        >
          {chipLabel(primaryStep)}
        </button>
      </div>
    </div>
  );
}

