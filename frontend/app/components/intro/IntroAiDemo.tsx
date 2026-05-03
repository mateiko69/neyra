"use client";

import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { useT } from "../i18n/I18nProvider";

type Props = {
  /** When true, stagger-in animations run (slide is visible). */
  isActive: boolean;
  reduceMotion: boolean | null;
};

export function IntroAiDemo({ isActive, reduceMotion }: Props) {
  const { t } = useT("IntroAiDemo");
  const [burst, setBurst] = useState(0);

  useEffect(() => {
    if (!isActive) return;
    setBurst((b) => b + 1);
  }, [isActive]);

  const items = [
    { id: "easy", labelKey: "ai.demo.style.easy", textKey: "ai.demo.suggestion.easy" },
    { id: "flirty", labelKey: "ai.demo.style.flirty", textKey: "ai.demo.suggestion.flirty" },
    { id: "deep", labelKey: "ai.demo.style.deep", textKey: "ai.demo.suggestion.deep" },
  ] as const;

  const staggerDelay = reduceMotion ? 0 : 0.14;
  const duration = reduceMotion ? 0.12 : 0.38;

  return (
    <div className="intro-ai-demo" aria-label={t("ai.demo.previewAria")}>
      <div className="intro-ai-demo__heading">
        <h1 className="intro-ai-demo__title">{t("ai.demo.title")}</h1>
        <p className="intro-ai-demo__desc">{t("ai.demo.subtitle")}</p>
      </div>

      <div className="intro-ai-demo__chat">
        <div className="intro-ai-demo__bubble-meta caption">{t("ai.demo.userLabel")}</div>
        <div className="intro-ai-demo__bubble-row">
          <div className="chat-message-bubble chat-message-bubble--own intro-ai-demo__bubble">
            <div className="chat-message-bubble__text">{t("ai.demo.userMessage")}</div>
          </div>
        </div>

        <div
          className="chat-first-opener chat-first-opener--in chat-first-opener--under-message intro-ai-demo__suggestions"
          aria-label={t("ai.demo.suggestionsBadge")}
        >
          <div className="chat-first-opener__badge">{t("ai.demo.suggestionsBadge")}</div>
          <div className="chat-first-opener__options chat-first-opener__options--inline chat-reply-styles" role="list">
            {items.map((item, i) => (
              <motion.div
                key={`${burst}-${item.id}`}
                role="listitem"
                className="intro-ai-demo__suggestion-wrap"
                initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 12 }}
                animate={isActive ? { opacity: 1, y: 0 } : { opacity: 0, y: reduceMotion ? 0 : 12 }}
                transition={{
                  duration,
                  delay: isActive ? i * staggerDelay : 0,
                  ease: [0.22, 1, 0.36, 1],
                }}
              >
                <div className="chat-reply-style intro-ai-demo__chip" tabIndex={-1}>
                  <span className="chat-reply-style__label">{t(item.labelKey)}</span>
                  <span className="chat-reply-style__text">{t(item.textKey)}</span>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
