"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiFetch } from "../../../lib/api";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { fetchLikesReceived, type LikeReceivedRow, type LikesPreviewLevel } from "../../../lib/likes/api";
import { useT } from "../i18n/I18nProvider";
import { Card, Button, Badge } from "../ui";
import { SafeImg } from "../SafeImg";
import { resolvePlanTier, isTierAtLeast } from "../../../lib/monetization/tiers";
import { recordInboundLikeMoment } from "../../../lib/monetization/valueMoments";
import { trackUserEvent } from "../../../lib/monetization/events";
import { EmptyState } from "../EmptyState";
import { consumeDailyBoost, fetchDailyBoosts } from "../../../lib/dailyBoosts";

type Viewer = { tier: "free" | "premium" | "premium_plus"; viewerId: number | null };

type LikesYouPanelProps = {
  /** Matches page uses an embedded, limited preview (reduced premium pressure). */
  variant?: "full" | "embedded";
  /** Max cards to display. Defaults depend on variant. */
  limit?: number;
  /** Optional: tell parent whether real likes exist (non-placeholder). */
  onHasRealLikes?: (hasLikes: boolean) => void;
};

function todayKey(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function freeRevealStorageKey(userId: number | null): string {
  return `likes:free_reveal:${userId ?? "anon"}:${todayKey()}`;
}

function maskName(seed: string): string {
  const s = (seed || "").trim();
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  const first = String.fromCharCode(65 + (h % 26));
  const last = String.fromCharCode(65 + ((h >>> 8) % 26));
  return `${first}***${last.toLowerCase()}`;
}

function formatDistanceKm(km: number | null): string {
  if (km == null || !Number.isFinite(km) || km <= 0) return "";
  return `${Math.trunc(km)} km away`;
}

function buildDemoRows(n: number): LikeReceivedRow[] {
  const hooks = ["likes.hook.travel", "likes.hook.music", "likes.hook.coffee"] as const;
  return Array.from({ length: n }, (_, i) => ({
    userId: `demo_${i + 1}`,
    age: null,
    city: "",
    distanceKm: 1 + i * 2,
    matchScore: 0,
    previewLevel: "blur",
    hasPhoto: false,
    photoUrl: null,
    hintKey: hooks[i % hooks.length],
  }));
}

export function LikesYouPanel({ variant = "full", limit, onHasRealLikes }: LikesYouPanelProps) {
  const { t } = useT("LikesYouPanel");
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [rows, setRows] = useState<LikeReceivedRow[]>([]);
  const [count, setCount] = useState(0);
  const [viewer, setViewer] = useState<Viewer>({ tier: "free", viewerId: null });
  const [paywallOpen, setPaywallOpen] = useState(false);
  const [clickedRow, setClickedRow] = useState<LikeReceivedRow | null>(null);
  const [unlocked, setUnlocked] = useState<Set<string>>(() => new Set());
  const loadedOnceRef = useRef(false);
  const blurViewedRef = useRef(false);

  useEffect(() => {
    if (loadedOnceRef.current) return;
    loadedOnceRef.current = true;
    let cancelled = false;
    setLoading(true);
    void (async () => {
      try {
        const [likes, sub, me] = await Promise.all([
          fetchLikesReceived({ limit: 6 }),
          apiFetch("/subscriptions/me", { metaReason: "likes-subscription", skipThrottle: true }).catch(() => null),
          apiFetch("/auth/me", { metaReason: "likes-viewer", skipThrottle: true }).catch(() => null),
        ]);
        if (cancelled) return;
        setRows(likes.likesReceived);
        setCount(likes.count);
        const meObj = me && typeof me === "object" ? (me as any) : null;
        const uid = meObj && Number.isFinite(Number(meObj.user_id ?? meObj.userId ?? meObj.id)) ? Math.trunc(Number(meObj.user_id ?? meObj.userId ?? meObj.id)) : null;
        const tier = resolvePlanTier(sub as any);
        setViewer({ tier, viewerId: uid && uid > 0 ? uid : null });
        if (likes.count > 0) {
          recordInboundLikeMoment();
          void trackAnalyticsEvent("likes_viewed", { count: likes.count, visible_cards: likes.likesReceived.length });
          void trackUserEvent("like_received", { count: likes.count, high_match: likes.likesReceived.some((r) => (r.matchScore ?? 0) >= 85) });
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const isPremium = isTierAtLeast(viewer.tier, "premium");
  const maxCards = Math.max(1, Math.min(variant === "embedded" ? 3 : 6, Number.isFinite(limit as any) ? Math.trunc(limit as any) : variant === "embedded" ? 3 : 6));

  const freeRevealUsed = useMemo(() => {
    return false;
  }, [viewer.viewerId]);

  // Free: 1 reveal/day via Daily Boosts (non-aggressive: still can browse blurred grid).
  const [dailyRevealRemaining, setDailyRevealRemaining] = useState<number>(0);
  useEffect(() => {
    let cancelled = false;
    void fetchDailyBoosts().then((b) => {
      if (cancelled) return;
      setDailyRevealRemaining(b?.reveal_remaining ?? 0);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  const canFreeReveal = variant !== "embedded";

  const effectivePreview = (row: LikeReceivedRow): LikesPreviewLevel => {
    if (isPremium) return "visible";
    if (unlocked.has(row.userId)) return "visible";
    return row.previewLevel;
  };

  const isRealRow = (row: LikeReceivedRow | null | undefined): row is LikeReceivedRow => {
    if (!row || typeof row !== "object") return false;
    const userId = String((row as any).userId || "").trim();
    if (!userId) return false;
    // Must have at least some real profile surface — avoid blank “ghost” cards.
    const hasPhoto = Boolean(String((row as any).photoUrl || "").trim());
    const hasAge = Number.isFinite(Number((row as any).age)) && Number((row as any).age) > 0;
    const hasCity = Boolean(String((row as any).city || "").trim());
    const hasDist = Number.isFinite(Number((row as any).distanceKm)) && Number((row as any).distanceKm) > 0;
    const hasCompat = Number.isFinite(Number((row as any).matchScore)) && Number((row as any).matchScore) > 0;
    return hasPhoto || hasAge || hasCity || hasDist || hasCompat;
  };

  const realRows = useMemo(() => (rows || []).filter(isRealRow), [rows]);

  useEffect(() => {
    if (loading) return;
    try {
      onHasRealLikes?.(realRows.length > 0);
    } catch {
      // ignore
    }
  }, [loading, onHasRealLikes, realRows.length]);

  useEffect(() => {
    if (loading || isPremium) return;
    if (count <= 0 && realRows.length <= 0) return;
    if (blurViewedRef.current) return;
    blurViewedRef.current = true;
    void trackAnalyticsEvent("likes_blur_viewed", {
      surface: variant === "embedded" ? "likes_you_embedded" : "likes_you_panel",
      count,
      visible_cards: realRows.length,
    });
  }, [loading, isPremium, count, realRows.length, variant]);

  const openPaywall = (row: LikeReceivedRow) => {
    setClickedRow(row);
    setPaywallOpen(true);
    void trackAnalyticsEvent("paywall_clicked", { source: "likes", surface: "likes_you_card_gate", variant: variant });
    void trackAnalyticsEvent("paywall_shown", { surface: "likes_upgrade_modal", variant: variant });
    void trackAnalyticsEvent("paywall_opened", { surface: "likes_you", count });
  };

  const onClickCard = (row: LikeReceivedRow) => {
    void trackAnalyticsEvent("blurred_card_clicked", { surface: "likes_you", preview_level: row.previewLevel, match_score: row.matchScore });
    if (isPremium) {
      router.push(`/people/${encodeURIComponent(String(row.userId))}`);
      return;
    }
    if (variant === "embedded") {
      // Embedded mode never does "tap to reveal" — keep UX simple and action-oriented.
      router.push("/premium?source=likes_you_embedded");
      return;
    }
    if (canFreeReveal && dailyRevealRemaining > 0) {
      void trackAnalyticsEvent("likes_daily_reveal_used", { surface: "likes_you", user_id: row.userId });
      void consumeDailyBoost("reveal").then((b) => setDailyRevealRemaining(b?.reveal_remaining ?? 0));
      router.push(`/people/${encodeURIComponent(String(row.userId))}?source=daily_reveal`);
      return;
    }
    openPaywall(row);
  };

  // Embedded (Matches): never show big empty grid / skeleton cards.
  if (!loading && variant === "embedded" && realRows.length === 0) {
    return (
      <section className="likes-you-panel likes-you-panel--embedded" aria-label={t("likes.aria")}>
        <Card className="surface" style={{ padding: 14 }}>
          <div className="section-label">{t("likes.emptyPreview.title")}</div>
          <div className="caption" style={{ marginTop: 6, opacity: 0.9 }}>
            {t("likes.emptyPreview.description")}
          </div>
          <div style={{ marginTop: 10 }}>
            <Link className="btn btn-secondary" href="/discover">
              {t("likes.emptyPreview.ctaDiscover")}
            </Link>
          </div>
        </Card>
      </section>
    );
  }

  if (!loading && count === 0) {
    return (
      <section className={["likes-you-panel", variant === "embedded" ? "likes-you-panel--embedded" : ""].filter(Boolean).join(" ")} aria-label={t("likes.aria")}>
        <div className="likes-you-panel__head">
          <div style={{ display: "grid", gap: 2 }}>
            <div className="likes-you-panel__title">{t("likes.title")}</div>
            <div className="caption likes-you-panel__sub">{t("likes.subtitleTeaser", { count: 3 })}</div>
          </div>
          <Link href="/premium?source=likes_you_empty_teaser" className="btn btn-primary">
            {t("likes.unlock")}
          </Link>
        </div>
        <div className="likes-you-panel__grid" aria-busy={false}>
          {buildDemoRows(3).map((row) => {
            const distValue = formatDistanceKm(row.distanceKm);
            const hint = row.hintKey ? t(row.hintKey) : "";
            const displayName = maskName(row.userId) || t("likes.newAdmirer");
            return (
              <Card
                key={row.userId}
                className={"likes-you-card surface likes-you-card--locked likes-you-card--no-photo"}
                onClick={() => router.push("/premium?source=likes_you_empty_card")}
                role="button"
                tabIndex={0}
                style={{ cursor: "pointer" }}
              >
                <div className="likes-you-card__media">
                  <div className="likes-you-card__placeholder" aria-hidden />
                  <div className="likes-you-card__overlay" />
                  <div className="likes-you-card__blurGlass" aria-hidden />
                  <div className="likes-you-card__top">
                    <Badge>{t("likes.card.likedYou")}</Badge>
                    <Badge tone="premium">{t("likes.card.newAdmirer")}</Badge>
                  </div>
                  <div className="likes-you-card__bottom">
                    <div className="likes-you-card__name">{displayName}</div>
                    {distValue ? <div className="likes-you-card__meta">{distValue}</div> : null}
                    {hint ? <div className="likes-you-card__hint">{hint}</div> : null}
                    <div className="likes-you-card__ctaRow">
                      <Button
                        type="button"
                        variant="primary"
                        className="likes-you-card__revealPulse"
                        onClick={(e) => {
                          e.stopPropagation();
                          router.push("/premium?source=likes_you_empty_reveal");
                        }}
                      >
                        {t("likes.card.reveal")}
                      </Button>
                    </div>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      </section>
    );
  }

  return (
    <section className={["likes-you-panel", variant === "embedded" ? "likes-you-panel--embedded" : ""].filter(Boolean).join(" ")} aria-label={t("likes.aria")}>
      <div className="likes-you-panel__head">
        <div style={{ display: "grid", gap: 2 }}>
          <div className="likes-you-panel__title">
            {t("likes.title")}{" "}
            {!loading && count > 0 ? (
              <Link href="/likes" className="likes-you-panel__count" style={{ color: "inherit", textDecoration: "underline", textUnderlineOffset: 3 }}>
                {t("likes.count", { count })}
              </Link>
            ) : null}
          </div>
          <div className="caption likes-you-panel__sub">
            {isPremium ? (
              t("likes.subtitlePremium")
            ) : count > 0 ? (
              <Link href="/likes" style={{ color: "inherit", textDecoration: "underline", textUnderlineOffset: 3 }}>
                {t("likes.subtitleTeaser", { count: Math.max(1, count) })}
              </Link>
            ) : (
              t("likes.subtitleTeaser", { count: Math.max(1, count) })
            )}
          </div>
        </div>
        {!isPremium && variant !== "embedded" ? (
          <Link href="/premium?source=likes_you" className="btn btn-primary" onClick={() => void trackAnalyticsEvent("paywall_clicked", { source: "likes", surface: "likes_you_header", count })}>
            {t("likes.unlock")}
          </Link>
        ) : null}
      </div>

      <div className="likes-you-panel__grid" aria-busy={loading}>
        {(loading ? [] : realRows).slice(0, maxCards).map((row: LikeReceivedRow, idx: number) => {
          const rawPreview = effectivePreview(row);
          const preview = variant === "embedded" && rawPreview === "blur" ? "partial" : rawPreview;
          const blurClass = preview === "visible" ? "" : preview === "partial" ? "blur-partial" : "blur-full";
          const match = row.matchScore;
          const ageValue = row.age ? String(row.age) : "";
          const cityValue = row.city ? String(row.city) : "";
          const distValue = formatDistanceKm(row.distanceKm);
          const age = ageValue || t("likes.fallback.ageHidden");
          const place = cityValue || distValue || t("likes.fallback.nearby");
          const metaBits = [age, place].filter(Boolean).join(" · ");
          const hint = row.hintKey ? t(row.hintKey) : "";
          const photo = row.photoUrl ? row.photoUrl : "";
          const rawName = String((row as any)?.displayName || "").trim();
          const displayName = isPremium && rawName ? rawName : maskName(row.userId) || t("likes.newAdmirer");
          const isLocked = !isPremium && preview !== "visible";
          const overlayText = isLocked ? t("likes.card.someoneLikedYou") : "";

          return (
            <Card
              key={row.userId}
              className={`likes-you-card surface ${isLocked ? "likes-you-card--locked" : "likes-you-card--premium"} ${!photo ? "likes-you-card--no-photo" : ""}`.trim()}
              onClick={() => onClickCard(row)}
              role="button"
              tabIndex={0}
              style={{ cursor: "pointer" }}
            >
              <div className="likes-you-card__media">
                {photo ? (
                  <SafeImg className={`likes-you-card__img ${blurClass}`.trim()} src={photo} alt="" loading="lazy" />
                ) : (
                  <div className="likes-you-card__placeholder" aria-hidden />
                )}
                <div className="likes-you-card__overlay" />
                {isLocked ? <div className="likes-you-card__blurGlass" aria-hidden /> : null}
                <div className="likes-you-card__top">
                  <Badge>{t("likes.card.likedYou")}</Badge>
                  {match > 0 ? <Badge tone="premium">{t("likes.matchPct", { pct: match })}</Badge> : null}
                  {isLocked ? <Badge tone="premium">{t("likes.card.newAdmirer")}</Badge> : null}
                </div>
                <div className="likes-you-card__bottom">
                  <div className="likes-you-card__name">{displayName}</div>
                  {distValue ? <div className="likes-you-card__meta">{distValue}</div> : metaBits ? <div className="likes-you-card__meta">{metaBits}</div> : null}
                  {hint ? <div className="likes-you-card__hint">{hint}</div> : null}
                  {isLocked ? (
                    <>
                      <div className="likes-you-card__lock caption">{overlayText}</div>
                      <div className="likes-you-card__lock caption">{t("likes.card.unlockHint")}</div>
                      <div className="likes-you-card__ctaRow">
                        <Button
                          type="button"
                          variant="primary"
                          className="likes-you-card__revealPulse"
                          onClick={(e) => {
                            e.stopPropagation();
                            openPaywall(row);
                          }}
                        >
                          {isPremium ? t("likes.card.reveal") : t("likes.card.seeWhoCta")}
                        </Button>
                      </div>
                    </>
                  ) : null}
                </div>
              </div>
            </Card>
          );
        })}
      </div>

      {!isPremium && variant === "embedded" ? (
        <div style={{ marginTop: 10, display: "flex", justifyContent: "flex-start" }}>
              <Link
                href="/premium?source=likes_you_embedded_cta"
                className="btn btn-primary"
                onClick={() =>
                  void trackAnalyticsEvent("paywall_clicked", { source: "likes", surface: "likes_you_embedded_cta", count })
                }
              >
                {t("likes.unlock")}
              </Link>
        </div>
      ) : null}

      {paywallOpen && variant !== "embedded" ? (
        <div className="likes-paywall" role="dialog" aria-modal="true" aria-label={t("likes.paywall.title")}>
          <div className="likes-paywall__backdrop" onClick={() => setPaywallOpen(false)} />
          <div className="likes-paywall__card">
            <div className="likes-paywall__title">{t("likes.paywall.title")}</div>
            <div className="likes-paywall__body">{t("likes.paywall.body", { count })}</div>
            <div className="likes-paywall__actions">
              <Link
                href="/premium?source=likes_you_paywall"
                className="btn btn-primary"
                onClick={() =>
                  void trackAnalyticsEvent("paywall_clicked", {
                    source: "likes",
                    surface: "likes_you_paywall_overlay",
                  })
                }
              >
                {t("likes.paywall.cta")}
              </Link>
              <Button type="button" variant="ghost" onClick={() => setPaywallOpen(false)}>
                {t("common.close")}
              </Button>
            </div>
            {clickedRow ? (
              <div className="caption" style={{ opacity: 0.82, marginTop: 12 }}>
                {t("likes.paywall.previewLine", { pct: clickedRow.matchScore })}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}

