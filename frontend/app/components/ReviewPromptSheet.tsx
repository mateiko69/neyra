"use client";

import { useState } from "react";
import { useT } from "./i18n/I18nProvider";
import { Toast } from "./ui";
import {
  markUserRatedApp,
  openFeedbackFormUrl,
  openReviewPrimaryAction,
  snoozeReviewPromptCooldown,
} from "../../lib/reviewPrompt";
import { trackAnalyticsEvent } from "../../lib/analytics";

type Props = {
  open: boolean;
  onClose: () => void;
};

/**
 * Bottom-sheet style prompt (not full-screen). 🇺🇦 copy defaults in uk locale.
 */
export function ReviewPromptSheet({ open, onClose }: Props) {
  const { t } = useT();
  const [toast, setToast] = useState("");

  if (!open) return null;

  const finishDismiss = () => {
    snoozeReviewPromptCooldown();
    onClose();
  };

  const onPositive = async () => {
    void trackAnalyticsEvent("review_positive_clicked", { surface: "review_prompt_sheet" });
    markUserRatedApp();
    await openReviewPrimaryAction({
      onCopied: () => setToast(t("reviewPrompt.copied")),
    });
    onClose();
  };

  const onNeutral = () => {
    void trackAnalyticsEvent("review_feedback_opened", { sentiment: "neutral", surface: "review_prompt_sheet" });
    snoozeReviewPromptCooldown();
    openFeedbackFormUrl();
    onClose();
  };

  const onNegative = () => {
    void trackAnalyticsEvent("review_feedback_opened", { sentiment: "negative", surface: "review_prompt_sheet" });
    snoozeReviewPromptCooldown();
    openFeedbackFormUrl();
    onClose();
  };

  return (
    <>
      <div className="review-prompt-sheet__wrap" aria-hidden={false}>
        <button type="button" className="review-prompt-sheet__scrim" aria-label={t("reviewPrompt.sheet.dismissAria")} onClick={() => finishDismiss()} />
        <div className="review-prompt-sheet__card surface" role="dialog" aria-modal="true" aria-labelledby="review-sheet-title">
          <p id="review-sheet-title" className="review-prompt-sheet__title">
            {t("reviewPrompt.sheet.title")}
          </p>
          <div className="review-prompt-sheet__actions">
            <button type="button" className="review-prompt-sheet__emoji-btn" onClick={() => void onPositive()}>
              <span className="review-prompt-sheet__emoji" aria-hidden>
                👍
              </span>
              <span>{t("reviewPrompt.sheet.positive")}</span>
            </button>
            <button type="button" className="review-prompt-sheet__emoji-btn" onClick={onNeutral}>
              <span className="review-prompt-sheet__emoji" aria-hidden>
                😐
              </span>
              <span>{t("reviewPrompt.sheet.neutral")}</span>
            </button>
            <button type="button" className="review-prompt-sheet__emoji-btn" onClick={onNegative}>
              <span className="review-prompt-sheet__emoji" aria-hidden>
                👎
              </span>
              <span>{t("reviewPrompt.sheet.negative")}</span>
            </button>
          </div>
        </div>
      </div>
      <Toast text={toast} onClose={() => setToast("")} />
    </>
  );
}
