"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { getToken } from "../../lib/api";
import { dismissDailyBanner, fetchDailyBoosts, type DailyBoosts } from "../../lib/dailyBoosts";
import { Button, Toast } from "./ui";
import { useT } from "./i18n/I18nProvider";

export function dailyBoostsBannerView(boosts: DailyBoosts | null, t: (k: string, vars?: Record<string, string | number>) => string) {
  const show = Boolean(boosts?.show_banner);
  const chips: string[] = [];
  if (boosts) {
    if (boosts.opener_remaining > 0) chips.push(t("dailyBoosts.chip.aiOpener"));
    if (boosts.reply_remaining > 0) {
      const n = Math.max(1, Math.trunc(Number(boosts.reply_remaining)));
      chips.push(n === 1 ? t("dailyBoosts.chip.aiReply.one") : t("dailyBoosts.chip.aiReply.many", { count: n }));
    }
    if (boosts.reveal_remaining > 0) chips.push(t("dailyBoosts.chip.reveal"));
    if (boosts.revive_remaining > 0) chips.push(t("dailyBoosts.chip.reviveChat"));
  }
  let streakLine: string | null = null;
  if (boosts) {
    const n = Math.max(0, Math.trunc(Number(boosts.streak_days ?? 0)));
    const bonus = Math.max(0, Math.trunc(Number(boosts.streak_bonus_ai_chat ?? 0)));
    if (n >= 2) {
      const extra = bonus > 0 ? t("dailyBoosts.streak.bonus", { count: bonus }) : "";
      streakLine = t("dailyBoosts.streak.line", { days: n, extra });
    }
  }
  return { show, chips, streakLine };
}

export function DailyBoostsBanner() {
  const { t } = useT("DailyBoostsBanner");
  const router = useRouter();
  const pathname = usePathname() || "/";
  const [boosts, setBoosts] = useState<DailyBoosts | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (pathname === "/") return;
    if (!getToken()) return;
    let cancelled = false;
    void fetchDailyBoosts().then((b) => {
      if (cancelled) return;
      setBoosts(b);
      if (b?.curiosity_like) {
        setToast(t("dailyBoosts.toast.curiosityLike"));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [pathname, t]);

  const view = useMemo(() => dailyBoostsBannerView(boosts, t), [boosts, t]);
  const show = view.show;
  const chips = useMemo(() => {
    return view.chips;
  }, [view.chips]);

  const streakLine = useMemo(() => {
    return view.streakLine;
  }, [view.streakLine]);

  const onCloseToast = useCallback(() => setToast(null), []);

  const onUseNow = useCallback(() => {
    const hasOpenerOrReply = (boosts?.opener_remaining || 0) > 0 || (boosts?.reply_remaining || 0) > 0;
    const hasReveal = (boosts?.reveal_remaining || 0) > 0;
    if (hasReveal) {
      router.push("/likes");
      return;
    }
    if (hasOpenerOrReply) {
      router.push("/matches");
      return;
    }
    setToast(t("dailyBoosts.toast.readyAnytime"));
  }, [boosts?.opener_remaining, boosts?.reply_remaining, boosts?.reveal_remaining, router, t]);

  const onDismiss = useCallback(() => {
    void dismissDailyBanner().then(setBoosts);
  }, []);

  if (!show) {
    return toast ? <Toast text={toast} onClose={onCloseToast} /> : null;
  }

  return (
    <>
      <div className="daily-boosts-banner" role="status" aria-live="polite">
        <div className="daily-boosts-banner__left">
          <div className="daily-boosts-banner__title">{t("dailyBoosts.banner.title")}</div>
          {streakLine ? <div className="daily-boosts-banner__streak">{streakLine}</div> : null}
          <div className="daily-boosts-banner__sub">{chips.join(` ${t("common.middleDot")} `)}</div>
        </div>
        <div className="daily-boosts-banner__actions">
          <Button
            type="button"
            variant="secondary"
            onClick={onUseNow}
          >
            {t("dailyBoosts.banner.useNow")}
          </Button>
          <button
            type="button"
            className="daily-boosts-banner__dismiss"
            aria-label={t("common.dismiss")}
            onClick={onDismiss}
          >
            ×
          </button>
        </div>
      </div>
      <Toast text={toast} onClose={onCloseToast} />
    </>
  );
}

