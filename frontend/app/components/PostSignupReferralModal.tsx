"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, getToken } from "../../lib/api";
import { trackAnalyticsEvent } from "../../lib/analytics";
import {
  clearPendingPostSignupReferral,
  isPendingPostSignupReferral,
  postSignupReferralSkipStorageKey,
} from "../../lib/referralSignupFlow";
import { useT } from "./i18n/I18nProvider";
import { Button, Toast } from "./ui";
import { ReferralShareModal } from "./ReferralShareModal";

type ReferralMe = { invite_link: string };

export function PostSignupReferralModal() {
  const { t } = useT("PostSignupReferralModal");
  const [welcomeOpen, setWelcomeOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [inviteLink, setInviteLink] = useState("");
  const [toast, setToast] = useState("");

  const tryOpenWelcome = useCallback(async () => {
    if (!getToken() || !isPendingPostSignupReferral()) return;
    try {
      const me = (await apiFetch("/auth/me", { method: "GET", skipAuthRedirect: true })) as { user_id?: number };
      const uid = me?.user_id;
      if (uid == null) return;
      try {
        if (localStorage.getItem(postSignupReferralSkipStorageKey(uid)) === "1") {
          clearPendingPostSignupReferral();
          return;
        }
      } catch {
        /* */
      }
      void trackAnalyticsEvent("referral_post_signup_modal_shown", {});
      setWelcomeOpen(true);
    } catch {
      /* */
    }
  }, []);

  useEffect(() => {
    const tmr = window.setTimeout(() => void tryOpenWelcome(), 400);
    return () => window.clearTimeout(tmr);
  }, [tryOpenWelcome]);

  const onSkip = useCallback(async () => {
    setWelcomeOpen(false);
    clearPendingPostSignupReferral();
    void trackAnalyticsEvent("referral_post_signup_modal_skip", {});
    try {
      const me = (await apiFetch("/auth/me", { method: "GET", skipAuthRedirect: true })) as { user_id?: number };
      const uid = me?.user_id;
      if (uid != null) localStorage.setItem(postSignupReferralSkipStorageKey(uid), "1");
    } catch {
      /* */
    }
  }, []);

  const onInviteUnlock = useCallback(async () => {
    void trackAnalyticsEvent("referral_post_signup_modal_invite_click", {});
    setWelcomeOpen(false);
    clearPendingPostSignupReferral();
    try {
      const r = (await apiFetch("/referrals/me", { metaReason: "referrals-me-post-signup", skipThrottle: true })) as ReferralMe | null;
      const link = r && typeof r.invite_link === "string" ? r.invite_link.trim() : "";
      if (link) {
        setInviteLink(link);
        setShareOpen(true);
      } else {
        setToast(t("referrals.loadError"));
      }
    } catch {
      setToast(t("referrals.loadError"));
    }
  }, [t]);

  const closeShare = useCallback(() => setShareOpen(false), []);

  if (!welcomeOpen && !shareOpen) return null;

  return (
    <>
      {welcomeOpen ? (
        <>
          <div className="post-signup-referral__backdrop" onClick={() => void onSkip()} aria-hidden />
          <div
            className="post-signup-referral__modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="post-signup-referral-title"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="post-signup-referral-title" className="post-signup-referral__title">
              {t("referrals.postSignup.title")}
            </h2>
            <p className="post-signup-referral__body">{t("referrals.postSignup.body")}</p>
            <div className="post-signup-referral__actions">
              <Button type="button" variant="primary" className="post-signup-referral__primary" onClick={() => void onInviteUnlock()}>
                {t("referrals.postSignup.inviteCta")}
              </Button>
              <Button type="button" variant="secondary" onClick={() => void onSkip()}>
                {t("referrals.postSignup.skip")}
              </Button>
            </div>
          </div>
        </>
      ) : null}
      <ReferralShareModal open={shareOpen} inviteLink={inviteLink} onClose={closeShare} />
      <Toast text={toast} onClose={() => setToast("")} />
    </>
  );
}
