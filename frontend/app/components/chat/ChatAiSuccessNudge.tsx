"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useT } from "../i18n/I18nProvider";

type Props = {
  message: string;
  ctaHref?: string | null;
  ctaLabel?: string | null;
  /** When true, do not navigate — call `onCtaClick` only (e.g. open AI panel). */
  ctaPreventNavigation?: boolean;
  onCtaClick?: (() => void) | null;
  onAutoDismiss: () => void;
  ttlMs?: number;
  /** Softer visual treatment for monetization hints (non-blocking). */
  appearance?: "default" | "soft";
};

export function ChatAiSuccessNudge({
  message,
  ctaHref = null,
  ctaLabel = null,
  ctaPreventNavigation = false,
  onCtaClick = null,
  onAutoDismiss,
  ttlMs = 4200,
  appearance = "default",
}: Props) {
  const show = Boolean((message ?? "").trim());
  const { t } = useT("ChatAiSuccessNudge");

  useEffect(() => {
    if (!show) return;
    const handle = window.setTimeout(() => onAutoDismiss(), Math.max(1200, ttlMs));
    return () => window.clearTimeout(handle);
  }, [onAutoDismiss, show, ttlMs]);

  if (!show) return null;

  const coachClass =
    appearance === "soft" ? "chat-coach chat-coach--soft-mon" : "chat-coach";

  return (
    <div className={coachClass} aria-label={t("chat.ai.success.aria")}>
      <div className="chat-coach__row">
        <div className="chat-coach__badge" aria-hidden>
          AI
        </div>
        <div className="chat-coach__text">
          {message}
          {ctaHref && ctaLabel ? (
            <>
              {" "}
              <Link
                href={ctaHref}
                className="chat-ai-inline__upgrade"
                onClick={(e) => {
                  if (ctaPreventNavigation) {
                    e.preventDefault();
                  }
                  try {
                    onCtaClick?.();
                  } catch {
                    // ignore
                  }
                }}
              >
                {ctaLabel}
              </Link>
            </>
          ) : null}
        </div>
        <button type="button" className="chat-coach__close" onClick={onAutoDismiss} aria-label={t("chat.ai.success.dismiss")}>
          ×
        </button>
      </div>
    </div>
  );
}

