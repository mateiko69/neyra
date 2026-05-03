"use client";

import { useMemo, useState } from "react";
import { useT } from "../i18n/I18nProvider";

export type Props = {
  score: number;
  level: "low" | "medium" | "high";
  insight: string;
  tips: string[];
  showScore?: boolean;
  onViewed: () => void;
  onUseTip?: (tip: string, index: number) => void;
};

export function ChatReadinessIndicator({ score, level, insight, tips, showScore = true, onViewed, onUseTip }: Props) {
  const [open, setOpen] = useState(false);
  const { t } = useT("ChatReadinessIndicator");

  const title = useMemo(() => {
    if (level === "high") return t("chat.ai.readiness.label.high");
    if (level === "low") return t("chat.ai.readiness.label.low");
    return t("chat.ai.readiness.label.medium");
  }, [level, t]);
  const scoreLabel = useMemo(() => {
    const s = Number.isFinite(score) ? Math.max(0, Math.min(100, Math.round(score))) : 0;
    return `${s}`;
  }, [score]);

  return (
    <div className="chat-ready">
      <button
        type="button"
        className="chat-ready__row"
        onClick={() => {
          setOpen((v) => {
            const next = !v;
            if (next) onViewed();
            return next;
          });
        }}
        aria-expanded={open}
        aria-label={t("chat.ai.readiness.aria")}
      >
        <span className="chat-ready__title">{title}</span>
        {showScore ? <span className="chat-ready__score">{scoreLabel}</span> : null}
        <span className="chat-ready__chev" aria-hidden>
          {open ? "▴" : "▾"}
        </span>
      </button>

      {open ? (
        <div className="chat-ready__panel">
          <div className="chat-ready__insight">{insight || t("chat.ai.readiness.fallbackInsight")}</div>
          {tips && tips.length > 0 ? (
            <div className="chat-ready__tips" aria-label={t("chat.ai.readiness.tipsAria")}>
              {tips.slice(0, 2).map((t, idx) => (
                <button
                  key={`${idx}:${t}`}
                  type="button"
                  className="chat-ready__tip"
                  onClick={() => onUseTip?.(t, idx)}
                >
                  {t}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

