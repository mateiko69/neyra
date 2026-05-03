"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, getToken } from "../../lib/api";
import { trackAnalyticsEvent } from "../../lib/analytics";
import { useT } from "./i18n/I18nProvider";
import { Button, Card, Toast } from "./ui";
import { CelebrationConfetti } from "./CelebrationConfetti";
import { ReferralShareModal } from "./ReferralShareModal";

type EarnedReward = {
  milestone_key: string;
  premium_days: number;
  granted_at: string | null;
};

type NextReward = {
  required: number;
  /** Server label (English); UI uses i18n from {@link required} instead. */
  reward: string;
  remaining: number;
  includes_discover_boost?: boolean;
};

type ReferralMe = {
  invite_link: string;
  referral_code: string;
  invites_count: number;
  joined_count: number;
  premium_rewards: unknown[];
  valid_referrals_count?: number;
  next_reward?: NextReward | null;
  earned_rewards?: EarnedReward[];
};

type ClaimRewardResponse = {
  status?: string;
  rewards?: { milestone_key?: string; premium_days?: number }[];
};

export type InviteFriendsCardProps = {
  source?: string;
  compact?: boolean;
  /** Full reward progress + claim (e.g. invite page). Hidden in compact profile surfaces. */
  showRewards?: boolean;
};

function nextRewardDays(required: number): number {
  if (required === 1) return 3;
  if (required === 3) return 7;
  if (required === 10) return 30;
  return 0;
}

function nextRewardLabel(t: (key: string, vars?: Record<string, string | number>) => string, nr: NextReward): string {
  if (nr.required === 1) return t("referrals.reward.premium3");
  if (nr.required === 3) return t("referrals.reward.premium7");
  if (nr.required === 10) return t("referrals.reward.premium30");
  return t("referrals.reward.premiumNext", { count: nr.required });
}

function earnedRewardLabel(t: (key: string, vars?: Record<string, string | number>) => string, e: EarnedReward): string {
  if (e.milestone_key === "refs_1") return t("referrals.reward.premium3");
  if (e.milestone_key === "refs_3") return t("referrals.reward.premium7");
  if (e.milestone_key === "refs_10") return t("referrals.reward.premium30");
  return t("referrals.reward.earnedFallback", { days: e.premium_days });
}

function ProgressBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div
      style={{
        height: 8,
        borderRadius: 999,
        background: "rgba(255,255,255,0.08)",
        overflow: "hidden",
        marginTop: 6,
      }}
    >
      <div
        style={{
          width: `${pct}%`,
          height: "100%",
          borderRadius: 999,
          background: "linear-gradient(90deg, rgba(120,200,255,0.9), rgba(180,140,255,0.95))",
          transition: "width 0.45s cubic-bezier(0.22, 1, 0.36, 1)",
        }}
      />
    </div>
  );
}

export function InviteFriendsCard({ source = "invite_card", compact = false, showRewards = false }: InviteFriendsCardProps) {
  const { t, locale } = useT("InviteFriendsCard");
  const [data, setData] = useState<ReferralMe | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [copied, setCopied] = useState(false);
  const [claimBusy, setClaimBusy] = useState(false);
  const [claimMsg, setClaimMsg] = useState<string | null>(null);
  const [shareOpen, setShareOpen] = useState(false);
  const [unlockToast, setUnlockToast] = useState("");
  const [confettiBurst, setConfettiBurst] = useState<number | null>(null);

  const load = useCallback(() => {
    if (!getToken()) return;
    setLoadError(false);
    void apiFetch("/referrals/me", { metaReason: "referrals-me", skipThrottle: true })
      .then((r) => {
        if (r && typeof r === "object" && "invite_link" in r) setData(r as ReferralMe);
        else setLoadError(true);
      })
      .catch(() => setLoadError(true));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    setClaimMsg(null);
  }, [locale]);

  const copy = async () => {
    if (!data?.invite_link) return;
    try {
      await navigator.clipboard.writeText(data.invite_link);
      void trackAnalyticsEvent("invite_link_copied", { source });
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2200);
    } catch {
      /* clipboard denied */
    }
  };

  const openShareModal = () => {
    if (!data?.invite_link) return;
    void trackAnalyticsEvent("referral_share_modal_opened", { source });
    setShareOpen(true);
  };

  const claimReward = async () => {
    if (!getToken()) return;
    setClaimBusy(true);
    setClaimMsg(null);
    try {
      const res = (await apiFetch("/referrals/claim-reward", {
        method: "POST",
        metaReason: "referrals-claim-reward",
        body: JSON.stringify({}),
      })) as ClaimRewardResponse;
      if (res && res.status === "awarded") {
        const days = (res.rewards ?? []).reduce((a, r) => a + (Number(r.premium_days) || 0), 0);
        setConfettiBurst(Date.now());
        setUnlockToast(days > 0 ? t("referrals.reward.daysUnlocked", { days }) : t("referrals.reward.claimed"));
        void load();
      } else {
        setClaimMsg(t("referrals.reward.noReward"));
      }
    } catch {
      setClaimMsg(t("referrals.loadError"));
    } finally {
      setClaimBusy(false);
      window.setTimeout(() => setClaimMsg(null), 3200);
    }
  };

  if (!getToken()) {
    return (
      <Card className="surface">
        <div className="section-label">{t("referrals.title")}</div>
        <p className="body muted" style={{ marginTop: 8, maxWidth: "62ch" }}>
          {t("referrals.loginPrompt")}
        </p>
        <div style={{ marginTop: 12 }}>
          <Button type="button" variant="secondary" onClick={() => (window.location.href = "/signup")}>
            {t("nav.signup")}
          </Button>
        </div>
      </Card>
    );
  }

  if (loadError || !data) {
    return (
      <Card className="surface">
        <div className="section-label">{t("referrals.title")}</div>
        <p className="body muted">{t("referrals.loadError")}</p>
        <Button type="button" variant="secondary" onClick={() => load()} style={{ marginTop: 10 }}>
          {t("common.tryAgain")}
        </Button>
      </Card>
    );
  }

  const valid = typeof data.valid_referrals_count === "number" ? data.valid_referrals_count : 0;
  const earned = Array.isArray(data.earned_rewards) ? data.earned_rewards : [];
  const next = data.next_reward ?? null;
  const progressFrac = next ? Math.min(1, valid / next.required) : 1;
  const progressLabel = next
    ? t("referrals.reward.progressToNext", {
        current: Math.min(valid, next.required),
        required: next.required,
        days: nextRewardDays(next.required),
      })
    : t("referrals.reward.allMilestonesDone");

  return (
    <Card className="surface" style={compact ? undefined : { maxWidth: "72ch" }}>
      {confettiBurst != null ? (
        <CelebrationConfetti key={confettiBurst} onDone={() => setConfettiBurst(null)} />
      ) : null}
      <div className="section-label">{t("referrals.title")}</div>
      <p className="body muted" style={{ marginTop: 8, maxWidth: "62ch", whiteSpace: "pre-line" }}>
        {t("referrals.subtitle")}
      </p>
      <p className="caption muted" style={{ marginTop: 10, maxWidth: "62ch", whiteSpace: "pre-line" }}>
        {t("referrals.body")}
      </p>
      {!compact ? (
        <p className="caption muted" style={{ marginTop: 8, maxWidth: "62ch", whiteSpace: "pre-line" }}>
          {t("referrals.safety")}
        </p>
      ) : null}

      {showRewards ? (
        <div style={{ marginTop: 18 }}>
          <div className="section-label">{t("referrals.reward.title")}</div>
          <p className="caption muted" style={{ marginTop: 8, maxWidth: "62ch" }}>
            {t("referrals.reward.blurb1", { reward: t("referrals.reward.premium3") })}
          </p>
          <p className="caption muted" style={{ marginTop: 6, maxWidth: "62ch" }}>
            {t("referrals.reward.blurb3", { reward: t("referrals.reward.premium7") })}
          </p>
          <p className="caption muted" style={{ marginTop: 6, maxWidth: "62ch" }}>
            {t("referrals.reward.blurb10", { reward: t("referrals.reward.premium30") })}
          </p>
          <div className="body" style={{ marginTop: 14 }}>
            {progressLabel}
            <ProgressBar value={progressFrac} />
          </div>
          {next ? (
            <p className="caption muted" style={{ marginTop: 12 }}>
              {t("referrals.reward.next", {
                reward: nextRewardLabel(t, next),
                remaining: next.remaining,
                inviteNoun: next.remaining === 1 ? t("referrals.reward.inviteSingular") : t("referrals.reward.invitePlural"),
              })}
            </p>
          ) : null}
          <div style={{ marginTop: 12 }}>
            <Button type="button" variant="secondary" disabled={claimBusy} onClick={() => void claimReward()}>
              {claimBusy ? t("common.loading") : t("referrals.reward.claim")}
            </Button>
            {claimMsg ? (
              <span className="caption muted" style={{ marginLeft: 12 }}>
                {claimMsg}
              </span>
            ) : null}
          </div>
          {earned.length ? (
            <div style={{ marginTop: 16 }}>
              <div className="section-label">{t("referrals.reward.earnedHeading")}</div>
              <ul className="body muted" style={{ marginTop: 8, paddingLeft: 18 }}>
                {earned.map((e) => (
                  <li key={`${e.milestone_key}-${e.granted_at ?? ""}`}>{earnedRewardLabel(t, e)}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      <div
        className="body"
        style={{
          marginTop: 14,
          padding: "10px 12px",
          borderRadius: 10,
          background: "rgba(255,255,255,0.06)",
          wordBreak: "break-all",
          fontSize: 13,
        }}
      >
        {data.invite_link}
      </div>
      <div className="caption muted" style={{ marginTop: 10 }}>
        {t("referrals.invitesCount", { count: data.invites_count })} · {t("referrals.joinedCount", { count: data.joined_count })}
      </div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14 }}>
        <Button type="button" onClick={() => void copy()}>
          {copied ? t("referrals.copied") : t("referrals.copyLink")}
        </Button>
        <Button type="button" variant="secondary" onClick={() => openShareModal()}>
          {t("referrals.share")}
        </Button>
      </div>
      <ReferralShareModal open={shareOpen} inviteLink={data.invite_link} onClose={() => setShareOpen(false)} />
      <Toast text={unlockToast} onClose={() => setUnlockToast("")} />
    </Card>
  );
}
