"use client";

import { useEffect, useRef } from "react";
import type { DiscoverEngagementDisplay } from "../../../lib/discover/engagementLoop";
import { useT } from "../../components/i18n/I18nProvider";

type Props = {
  engagement: DiscoverEngagementDisplay;
  /** Increment when a like is recorded to play a subtle pulse */
  pulseToken: number;
};

export function DiscoverEngagementBar({ engagement, pulseToken }: Props) {
  const { t } = useT("DiscoverEngagementBar");
  const rootRef = useRef<HTMLDivElement>(null);
  const prevPulse = useRef(pulseToken);

  useEffect(() => {
    if (pulseToken === prevPulse.current) return;
    prevPulse.current = pulseToken;
    const el = rootRef.current;
    if (!el) return;
    el.classList.remove("discover-engagement-bar--pulse");
    void el.offsetWidth;
    el.classList.add("discover-engagement-bar--pulse");
    const id = window.setTimeout(() => el.classList.remove("discover-engagement-bar--pulse"), 520);
    return () => window.clearTimeout(id);
  }, [pulseToken]);

  const { todayLikes, streakDays, likesForBoostRemaining, boostUnlocked } = engagement;

  return (
    <div
      ref={rootRef}
      className="discover-engagement-bar"
      role="status"
      aria-live="polite"
      aria-label={t("discover.engagement.aria")}
    >
      <div className="discover-engagement-bar__inner">
        {streakDays > 0 ? (
          <span className="discover-engagement-bar__streak" title={t("discover.engagement.streak", { count: streakDays })}>
            🔥 {t("discover.engagement.streak", { count: streakDays })}
          </span>
        ) : null}
        {streakDays > 0 ? <span className="discover-engagement-bar__dot" aria-hidden /> : null}
        <span className="discover-engagement-bar__likes">{t("discover.engagement.likesToday", { count: todayLikes })}</span>
        <span className="discover-engagement-bar__dot" aria-hidden />
        <span className="discover-engagement-bar__goal">
          {boostUnlocked
            ? t("discover.engagement.boostUnlocked")
            : t("discover.engagement.goalMoreLikes", { count: likesForBoostRemaining })}
        </span>
      </div>
    </div>
  );
}
