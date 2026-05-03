"use client";

import { useCallback, useMemo, useState } from "react";
import { openerShareTelegramUrl, openerShareWhatsAppUrl } from "../../lib/viralShare";
import { trackAnalyticsEvent } from "../../lib/analytics";
import { useT } from "./i18n/I18nProvider";
import { Button, Toast } from "./ui";

type Props = {
  open: boolean;
  inviteLink: string;
  onClose: () => void;
};

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function ReferralShareModal({ open, inviteLink, onClose }: Props) {
  const { t } = useT("ReferralShareModal");
  const [toast, setToast] = useState("");

  const shareText = useMemo(() => t("referrals.share.viralBody", { link: inviteLink.trim() }), [t, inviteLink]);

  const track = useCallback((channel: string) => {
    void trackAnalyticsEvent("referral_viral_share_channel", { channel });
  }, []);

  const onTelegram = useCallback(() => {
    track("telegram");
    window.open(openerShareTelegramUrl(shareText), "_blank", "noopener,noreferrer");
  }, [shareText, track]);

  const onWhatsApp = useCallback(() => {
    track("whatsapp");
    window.open(openerShareWhatsAppUrl(shareText), "_blank", "noopener,noreferrer");
  }, [shareText, track]);

  const onInstagram = useCallback(async () => {
    track("instagram");
    const ok = await copyText(shareText);
    setToast(ok ? t("chat.shareModal.copied") : t("chat.shareModal.copyFailed"));
    window.open("https://www.instagram.com/", "_blank", "noopener,noreferrer");
  }, [shareText, t, track]);

  const onMessenger = useCallback(async () => {
    track("messenger");
    const ok = await copyText(shareText);
    setToast(ok ? t("chat.shareModal.copied") : t("chat.shareModal.copyFailed"));
    window.open("https://www.messenger.com/", "_blank", "noopener,noreferrer");
  }, [shareText, t, track]);

  const onCopyLink = useCallback(async () => {
    track("copy_link");
    const ok = await copyText(inviteLink.trim());
    setToast(ok ? t("chat.shareModal.linkCopied") : t("chat.shareModal.copyFailed"));
  }, [inviteLink, t, track]);

  if (!open) return null;

  return (
    <>
      <div className="viral-share-modal__backdrop" onClick={onClose} aria-hidden />
      <div
        className="viral-share-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="referral-share-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="viral-share-modal__head">
          <h2 id="referral-share-modal-title" className="viral-share-modal__title">
            {t("referrals.shareModal.title")}
          </h2>
          <button type="button" className="viral-share-modal__close" onClick={onClose} aria-label={t("common.close")}>
            ×
          </button>
        </div>
        <p className="viral-share-modal__preview caption">{shareText}</p>
        <div className="viral-share-modal__grid">
          <Button type="button" variant="secondary" className="viral-share-modal__btn" onClick={onTelegram}>
            {t("chat.shareModal.telegram")}
          </Button>
          <Button type="button" variant="secondary" className="viral-share-modal__btn" onClick={onWhatsApp}>
            {t("chat.shareModal.whatsapp")}
          </Button>
          <Button type="button" variant="secondary" className="viral-share-modal__btn" onClick={onInstagram}>
            {t("chat.shareModal.instagram")}
          </Button>
          <Button type="button" variant="secondary" className="viral-share-modal__btn" onClick={onMessenger}>
            {t("chat.shareModal.messenger")}
          </Button>
          <Button type="button" variant="primary" className="viral-share-modal__btn viral-share-modal__btn--wide" onClick={() => void onCopyLink()}>
            {t("chat.shareModal.copyLink")}
          </Button>
        </div>
      </div>
      <Toast text={toast} onClose={() => setToast("")} />
    </>
  );
}
