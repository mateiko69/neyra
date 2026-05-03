"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../../lib/api";
import { shareOrCopy, withViralShareAttribution } from "../../lib/viralShare";
import { generateViralMomentImage } from "../../lib/viralMomentImage";
import { Card, Button, Toast } from "./ui";
import { useT } from "./i18n/I18nProvider";
import { trackAnalyticsEvent } from "../../lib/analytics";

type Props = {
  open: boolean;
  /** AI suggestion line (legacy prop name). */
  aiText: string;
  partnerMessage?: string;
  resultText?: string;
  onClose: () => void;
  onRewarded?: (days: number) => void;
};

export function ViralMomentShareModal({ open, aiText, partnerMessage = "", resultText = "", onClose, onRewarded }: Props) {
  const { t } = useT("ViralMomentShareModal");
  const [inviteLink, setInviteLink] = useState<string>("");
  const [imgUrl, setImgUrl] = useState<string>("");
  const [imgBlob, setImgBlob] = useState<Blob | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const shareUrl = useMemo(() => withViralShareAttribution(inviteLink.trim() || "https://neyra.app/signup"), [inviteLink]);

  const shareText = useMemo(() => {
    return t("referrals.share.shareTextViral", { link: shareUrl });
  }, [shareUrl, t]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setImgUrl("");
    setImgBlob(null);
    void apiFetch("/referrals/me", { metaReason: "viral-moment-ref", skipThrottle: true })
      .then((r) => {
        if (cancelled) return;
        const link = r && typeof r === "object" ? String((r as any).invite_link || "") : "";
        setInviteLink(link);
      })
      .catch(() => {
        if (!cancelled) setInviteLink("");
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      try {
        const { blob, dataUrl } = await generateViralMomentImage({
          partnerMessage: partnerMessage || t("viral.image.placeholderThem"),
          aiReply: aiText,
          resultText: resultText || aiText,
          labels: {
            them: t("viral.image.labelThem"),
            ai: t("viral.image.labelAi"),
            you: t("viral.image.labelYou"),
          },
        });
        if (cancelled) return;
        setImgBlob(blob);
        setImgUrl(dataUrl);
      } catch {
        // ignore
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [aiText, open, partnerMessage, resultText, t]);

  if (!open) return null;

  async function rewardFirstShare() {
    try {
      const r = await apiFetch("/referrals/first-share", { method: "POST", metaReason: "viral-first-share", skipThrottle: true, body: JSON.stringify({}) });
      if (r && typeof r === "object" && (r as any).status === "awarded") {
        const days = Number((r as any).premium_days ?? 3);
        onRewarded?.(Number.isFinite(days) ? days : 3);
      }
    } catch {
      // ignore
    }
  }

  async function nativeShare() {
    try {
      const nav = globalThis.navigator as Navigator & { share?: (data: ShareData) => Promise<void> };
      if (imgBlob && typeof nav.share === "function" && typeof File !== "undefined") {
        const file = new File([imgBlob], "neyra-moment.png", { type: "image/png" });
        await nav.share({ title: "NEYRA", text: shareText, url: shareUrl, files: [file] });
        void rewardFirstShare();
        void trackAnalyticsEvent("share_sent", { surface: "viral_moment_modal", channel: "native_share" });
        setToast(t("referrals.share.toast.rewarded", { days: 3 }));
        return;
      }
    } catch {
      // fall back
    }
    const ok = await shareOrCopy({ title: "NEYRA", text: shareText, url: shareUrl, analyticsName: "share_sent" });
    if (ok) {
      void rewardFirstShare();
      setToast(t("referrals.share.toast.rewarded", { days: 3 }));
    } else {
      setToast(t("errors.share.tryCopyLink"));
    }
  }

  return (
    <>
      <div className="post-signup-referral__backdrop" role="dialog" aria-modal="true" onClick={onClose}>
        <Card className="surface post-signup-referral__modal" onClick={(e) => e.stopPropagation()}>
          <div className="h2" style={{ fontSize: 22, fontWeight: 900, letterSpacing: "-0.03em" }}>
            {t("referrals.share.title")}
          </div>
          <div className="subtitle" style={{ marginTop: 8, opacity: 0.86 }}>
            {t("referrals.share.subtitle")}
          </div>

          {imgUrl ? (
            <div style={{ marginTop: 12, borderRadius: 16, overflow: "hidden", border: "1px solid rgba(255,255,255,0.12)" }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={imgUrl} alt={t("referrals.share.previewAlt")} style={{ width: "100%", display: "block" }} />
            </div>
          ) : null}

          <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
            <Button type="button" onClick={() => void nativeShare()}>
              {t("common.share")}
            </Button>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  void trackAnalyticsEvent("share_sent", { surface: "viral_moment_modal", channel: "telegram_web" });
                  window.location.href = `https://t.me/share/url?text=${encodeURIComponent(shareText)}`;
                }}
              >
                {t("common.social.telegram")}
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  void trackAnalyticsEvent("share_sent", { surface: "viral_moment_modal", channel: "whatsapp_web" });
                  window.location.href = `https://api.whatsapp.com/send?text=${encodeURIComponent(shareText)}`;
                }}
              >
                {t("common.social.whatsapp")}
              </Button>
              <Button type="button" variant="secondary" onClick={() => setToast(t("referrals.share.toast.openInstagram"))}>
                {t("common.social.instagram")}
              </Button>
              <Button type="button" variant="secondary" onClick={() => setToast(t("referrals.share.toast.openMessenger"))}>
                {t("common.social.messenger")}
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(shareUrl);
                    void rewardFirstShare();
                    void trackAnalyticsEvent("share_sent", { surface: "viral_moment_modal", channel: "copy_link" });
                    setToast(t("referrals.share.toast.copiedRewarded", { days: 3 }));
                  } catch {
                    setToast(t("errors.clipboard.copyFailed"));
                  }
                }}
              >
                {t("common.copyLink")}
              </Button>
              <Button type="button" variant="ghost" onClick={onClose}>
                {t("common.close")}
              </Button>
            </div>
          </div>
        </Card>
      </div>
      <Toast text={toast} onClose={() => setToast(null)} />
    </>
  );
}
