"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { ChatThreadHeaderSeed } from "../../../lib/chat/threadHeaderSeed";
import type { ChatPartnerProfile } from "../../../lib/chat/types";
import { fetchProfileTrust, type ProfileTrust } from "../../../lib/trust/api";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { useT } from "../i18n/I18nProvider";
import { Skeleton } from "../ui";
import { VerifiedBadge } from "../trust/VerifiedBadge";
import { ChatAvatar } from "./ChatAvatar";

type ChatHeaderProps = {
  partnerUserId: number;
  partner: ChatPartnerProfile | null;
  /** From inbox / matches / profile tap - keeps header stable while profile GET completes. */
  seed: ChatThreadHeaderSeed | null;
  showSkeleton: boolean;
  planTier: "free" | "premium" | "premium_plus";
  /** ISO timestamp from thread payload (partner `last_active_at`). */
  partnerLastActiveAt?: string | null;
};

export function ChatHeader({ partnerUserId, partner, seed, showSkeleton, planTier, partnerLastActiveAt }: ChatHeaderProps) {
  const { t } = useT("ChatHeader");
  const [trust, setTrust] = useState<ProfileTrust | null>(null);
  const isDemoProfile = Boolean(partner?.isDemoProfile);

  useEffect(() => {
    if (isDemoProfile) {
      setTrust(null);
      return;
    }
    let cancelled = false;
    setTrust(null);
    void (async () => {
      try {
        const next = await fetchProfileTrust({ userId: partnerUserId });
        if (!cancelled) setTrust(next);
      } catch {
        if (!cancelled) setTrust(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isDemoProfile, partnerUserId]);

  if (showSkeleton) {
    return (
      <div className="chat-header" aria-busy>
        <Skeleton className="chat-header__avatar-skeleton" style={{ width: 64, height: 64, borderRadius: 20, flexShrink: 0 }} />
        <div className="chat-header__meta">
          <Skeleton style={{ width: 84, height: 10, borderRadius: 999 }} />
          <Skeleton style={{ width: 168, height: 22, borderRadius: 12, marginTop: 10 }} />
          <Skeleton style={{ width: 120, height: 12, borderRadius: 999, marginTop: 10 }} />
        </div>
      </div>
    );
  }

  const partnerName = partner?.displayName?.trim() ?? "";
  const seedName = seed?.displayName?.trim() ?? "";
  const displayName = partnerName || seedName || t("chat.header.fallbackName");

  const partnerPhoto = partner?.primaryPhotoUrl?.trim() ?? "";
  const photoSrc = (partnerPhoto.length > 0 ? partnerPhoto : null) ?? seed?.avatarUrl ?? null;

  const activeMs = partnerLastActiveAt ? Date.parse(partnerLastActiveAt) : NaN;
  const recentlyActive = Number.isFinite(activeMs) && Date.now() - activeMs < 5 * 60 * 1000;
  const lastSeenLabel = (() => {
    if (!partnerLastActiveAt || recentlyActive) return null;
    const d = new Date(activeMs);
    if (Number.isNaN(d.getTime())) return null;
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  })();

  const metaParts = [
    partner?.age != null ? `${partner.age}` : null,
    partner?.city?.trim() || null,
    recentlyActive ? t("chat.header.activeNow") : lastSeenLabel ? t("chat.header.lastSeen", { time: lastSeenLabel }) : null,
  ].filter(Boolean);
  const subtitle =
    metaParts.length > 0
      ? metaParts.join(" · ")
      : partner
        ? t("chat.header.openProfile")
        : t("chat.header.matchedProfile");

  const isVerified = !isDemoProfile && Boolean(trust?.is_verified);

  return (
    <Link
      href={`/people/${partnerUserId}`}
      className={`chat-header chat-header--interactive ${isVerified ? "trust-verified" : ""}`.trim()}
      prefetch={false}
      onClick={() => {
        if (!isVerified) return;
        void trackAnalyticsEvent("verified_profile_clicked", {
          plan_tier: planTier,
          surface: "chat_header",
          user_id: partnerUserId,
        });
      }}
    >
      <ChatAvatar
        className="chat-avatar chat-avatar--header"
        name={displayName}
        src={photoSrc ?? undefined}
        alt={t("chat.header.avatarAlt", { name: displayName })}
      />

      <div className="chat-header__meta">
        <div className="chat-header__eyebrow">{t("chat.header.eyebrow")}</div>
        <div className="chat-header__name">
          {displayName}
          {isVerified ? <VerifiedBadge size="md" title={t("trust.verified.tooltip")} className="chat-header__verified-icon" /> : null}
        </div>
        <div className="chat-header__subtitle">{isDemoProfile ? t("demo.profile.label") : subtitle}</div>
        <div className="caption" style={{ marginTop: 6, opacity: 0.88 }}>
          {isDemoProfile ? t("demo.chat.disclaimer") : isVerified ? t("trust.chat.verifiedLine") : t("trust.chat.unverifiedLine")}
        </div>
      </div>

      <span className="chat-header__action" aria-hidden>
        {t("chat.header.view")}
      </span>
    </Link>
  );
}
