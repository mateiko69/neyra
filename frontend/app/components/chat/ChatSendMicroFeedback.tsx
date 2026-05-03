"use client";

import { useEffect, useState } from "react";
import { useT } from "../i18n/I18nProvider";

type Phase = "typing" | "message";

type Props = {
  onDone: () => void;
};

/** Subtle post-send line: brief typing dots (300–600ms), then a short positive note. */
export function ChatSendMicroFeedback({ onDone }: Props) {
  const { t } = useT("ChatSendMicroFeedback");
  const [phase, setPhase] = useState<Phase>("typing");

  useEffect(() => {
    const reduced =
      typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const typingMs = reduced ? 0 : 300 + Math.floor(Math.random() * 300);
    const visibleMs = reduced ? 1600 : 2000;
    const toMessage = window.setTimeout(() => setPhase("message"), typingMs);
    const finish = window.setTimeout(() => onDone(), typingMs + visibleMs);
    return () => {
      window.clearTimeout(toMessage);
      window.clearTimeout(finish);
    };
  }, [onDone]);

  return (
    <div
      className="chat-send-micro-feedback"
      aria-live="polite"
      aria-atomic="true"
      aria-relevant="additions text"
    >
      {phase === "typing" ? (
        <div className="chat-send-micro-feedback__typing" aria-label={t("chat.sendFeedback.typingAria")}>
          <span />
          <span />
          <span />
        </div>
      ) : (
        <p className="chat-send-micro-feedback__text">{t("chat.sendFeedback.message")}</p>
      )}
    </div>
  );
}
