"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch, getToken, invalidateApiGetCache } from "../../../lib/api";
import type { NavBadgesResponse } from "../../../lib/nav-config";
import { setNavBadgesFromServer } from "../../../lib/navBadgesStore";
import {
  fetchLikesIncoming,
  hideIncomingLike,
  respondToIncomingLike,
  revealIncomingLike,
  type IncomingLikeItem,
} from "../../../lib/likes/api";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { recordInboundLikeMoment } from "../../../lib/monetization/valueMoments";
import { PageHeader } from "../../components/PageHeader";
import { PageShell } from "../../components/PageShell";
import { SafeImg } from "../../components/SafeImg";
import { useT } from "../../components/i18n/I18nProvider";
import { Badge, Button, Card } from "../../components/ui";
import { PremiumUpgradeModal } from "../../components/monetization/PremiumUpgradeModal";

type PartnerPublicLite = {
  user_id: number;
  display_name: string;
  age: number | null;
  city: string;
  bio: string;
  interests: string[];
  lifestyle_tags: string[];
  photo_urls: string[];
};

export default function LikesPage() {
  const { t } = useT("LikesPage");
  const router = useRouter();
  const incomingPaywallShownRef = useRef(false);
  const likesBlurViewedRef = useRef(false);
  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState<IncomingLikeItem[]>([]);
  const [waiting, setWaiting] = useState(0);
  const [premium, setPremium] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paywallOpen, setPaywallOpen] = useState(false);
  const [revealedUserId, setRevealedUserId] = useState<number | null>(null);
  const [revealedProfile, setRevealedProfile] = useState<PartnerPublicLite | null>(null);
  const [respondBusy, setRespondBusy] = useState<"like" | "pass" | null>(null);
  const [matchChatUrl, setMatchChatUrl] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const r = await fetchLikesIncoming({ limit: 48 });
      setItems(r.items);
      setWaiting(r.waiting_count);
      setPremium(r.is_premium);
      if (!r.is_premium && (r.waiting_count > 0 || r.items.length > 0)) {
        recordInboundLikeMoment();
      }
      void trackAnalyticsEvent("likes_screen_open", {
        waiting: r.waiting_count,
        premium: r.is_premium,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!matchChatUrl || revealedUserId == null || revealedUserId <= 0) return;
    try {
      sessionStorage.setItem(`neyra_match_partner_ts:${revealedUserId}`, String(Date.now()));
    } catch {
      /* ignore */
    }
  }, [matchChatUrl, revealedUserId]);

  useEffect(() => {
    if (loading || premium) return;
    if (!items.length) return;
    if (likesBlurViewedRef.current) return;
    likesBlurViewedRef.current = true;
    void trackAnalyticsEvent("likes_blur_viewed", { surface: "likes_incoming_page", waiting_count: waiting });
  }, [loading, premium, items.length, waiting]);

  useEffect(() => {
    if (loading) return;
    if (premium) return;
    if (waiting <= 0) return;
    if (incomingPaywallShownRef.current) return;
    incomingPaywallShownRef.current = true;
    void trackAnalyticsEvent("paywall_shown", { surface: "likes_incoming_blur_grid", waiting_count: waiting });
  }, [loading, premium, waiting]);

  const onHide = async (userId: number) => {
    try {
      await hideIncomingLike(userId);
      setItems((prev) => prev.filter((x) => x.user_id !== userId));
      setWaiting((w) => Math.max(0, w - 1));
      void trackAnalyticsEvent("likes_hide", { user_id: userId });
    } catch {
      // ignore
    }
  };

  const onReveal = async (userId: number) => {
    if (!premium) {
      void trackAnalyticsEvent("paywall_clicked", { source: "likes", surface: "likes_card_see_who", user_id: userId });
      void trackAnalyticsEvent("paywall_shown", { surface: "likes_upgrade_modal" });
      setPaywallOpen(true);
      return;
    }
    const r = await revealIncomingLike(userId);
    if (r.ok) {
      setRevealedUserId(userId);
      setRevealedProfile(null);
      try {
        const profile = await apiFetch(`/profiles/partner/${userId}`, {
          method: "GET",
          metaReason: `likes-reveal-profile-${userId}`,
          skipThrottle: true,
          skipCache: true,
        });
        const obj = profile && typeof profile === "object" ? (profile as Record<string, unknown>) : {};
        setRevealedProfile({
          user_id: Math.max(0, Math.trunc(Number(obj.user_id ?? userId))),
          display_name: String(obj.display_name ?? "").trim() || "Unknown",
          age: obj.age != null && Number.isFinite(Number(obj.age)) ? Math.trunc(Number(obj.age)) : null,
          city: String(obj.city ?? "").trim(),
          bio: String(obj.bio ?? "").trim(),
          interests: Array.isArray(obj.interests) ? (obj.interests as unknown[]).map((x) => String(x)) : [],
          lifestyle_tags: Array.isArray(obj.lifestyle_tags)
            ? (obj.lifestyle_tags as unknown[]).map((x) => String(x))
            : [],
          photo_urls: Array.isArray(obj.photo_urls) ? (obj.photo_urls as unknown[]).map((x) => String(x)) : [],
        });
      } catch {
        setRevealedProfile(null);
      }
      return;
    }
    void trackAnalyticsEvent("likes_reveal_paywall", { user_id: userId });
    setPaywallOpen(true);
  };

  const invalidateMatchRelated = useCallback(() => {
    invalidateApiGetCache("/matches");
    invalidateApiGetCache("/messages/conversations");
    invalidateApiGetCache("/nav/badges");
  }, []);

  const onRespond = async (action: "like" | "pass") => {
    if (revealedUserId == null || respondBusy) return;
    setRespondBusy(action);
    try {
      const r = await respondToIncomingLike(revealedUserId, action);
      invalidateMatchRelated();
      if (action === "like" && r.matched) {
        try {
          const [badges] = await Promise.all([
            apiFetch("/nav/badges", {
              metaReason: "likes-like-back-badges",
              skipCache: true,
              skipThrottle: true,
            }),
            apiFetch("/messages/conversations", {
              metaReason: "likes-like-back-conversations",
              skipCache: true,
              skipThrottle: true,
            }).catch(() => null),
            apiFetch("/matches", {
              metaReason: "likes-like-back-matches",
              skipCache: true,
              skipThrottle: true,
            }).catch(() => null),
          ]);
          setNavBadgesFromServer(badges as NavBadgesResponse, "likes-like-back");
        } catch {
          /* ignore */
        }
      }
      void load();
      if (action === "pass") {
        setRevealedUserId(null);
        setRevealedProfile(null);
        return;
      }
      if (r.matched && r.chat_url) {
        setMatchChatUrl(String(r.chat_url));
      }
    } finally {
      setRespondBusy(null);
    }
  };

  const formatDist = (km: number | null) => {
    if (km != null && Number.isFinite(km) && km > 0) return t("likes.page.distance", { km: Math.trunc(km) });
    return t("likes.page.distanceUnknown");
  };

  return (
    <PageShell>
      <PremiumUpgradeModal open={paywallOpen} onClose={() => setPaywallOpen(false)} source="likes_screen_paywall_see_who" />
      <PageHeader
        title={t("likes.page.title")}
        subtitle={t(premium ? "likes.page.subtitle" : waiting > 0 ? "likes.page.paywallSubtitle" : "likes.page.subtitle")}
      />

      <section aria-label={t("likes.page.title")}>
        {revealedProfile ? (
          <Card className="surface" style={{ marginBottom: 14, padding: 14 }}>
            <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
              <div style={{ width: 84, height: 104, borderRadius: 14, overflow: "hidden", background: "rgba(255,255,255,0.06)" }}>
                {revealedProfile.photo_urls?.[0] ? (
                  <SafeImg
                    className=""
                    src={revealedProfile.photo_urls[0]}
                    alt=""
                    loading="lazy"
                    style={{ width: "100%", height: "100%", objectFit: "cover" }}
                  />
                ) : (
                  <div aria-hidden style={{ width: "100%", height: "100%" }} />
                )}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: 16 }}>
                  {revealedProfile.display_name}
                  {revealedProfile.age != null ? `, ${revealedProfile.age}` : ""}
                </div>
                <div className="body" style={{ marginTop: 2, opacity: 0.9 }}>
                  {revealedProfile.city || t("likes.page.distanceUnknown")}
                </div>
                {revealedProfile.bio ? (
                  <div className="body" style={{ marginTop: 8, opacity: 0.92 }}>
                    {revealedProfile.bio}
                  </div>
                ) : null}
                {revealedProfile.interests.length || revealedProfile.lifestyle_tags.length ? (
                  <div style={{ marginTop: 10, display: "flex", flexWrap: "wrap", gap: 8 }}>
                    {[...revealedProfile.interests, ...revealedProfile.lifestyle_tags].slice(0, 10).map((x) => (
                      <Badge key={x}>{x}</Badge>
                    ))}
                  </div>
                ) : null}
                <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <Button type="button" variant="primary" disabled={respondBusy != null} onClick={() => void onRespond("like")}>
                    {respondBusy === "like" ? t("common.loading") : t("likes.page.likeBack")}
                  </Button>
                  <Button type="button" variant="ghost" disabled={respondBusy != null} onClick={() => void onRespond("pass")}>
                    {t("likes.page.pass")}
                  </Button>
                  <Button type="button" variant="ghost" disabled={respondBusy != null} onClick={() => router.push(`/people/${revealedProfile.user_id}`)}>
                    {t("likes.page.openProfile")}
                  </Button>
                </div>
              </div>
            </div>
          </Card>
        ) : null}

        {matchChatUrl ? (
          <div
            role="dialog"
            aria-modal="true"
            style={{
              position: "fixed",
              inset: 0,
              zIndex: 60,
              background: "rgba(0,0,0,0.66)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: 18,
            }}
          >
            <Card className="surface" style={{ width: "min(520px, 100%)", padding: 18 }}>
              <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 6 }}>{t("likes.match.title")}</div>
              <div className="body" style={{ margin: 0, opacity: 0.92 }}>
                {t("likes.match.subtitle")}
              </div>
              <div style={{ marginTop: 14, display: "flex", gap: 10, flexWrap: "wrap" }}>
                <Button
                  type="button"
                  variant="primary"
                  onClick={() => {
                    const url = matchChatUrl;
                    setMatchChatUrl(null);
                    if (url) router.push(url);
                  }}
                >
                  {t("likes.match.openChat")}
                </Button>
                <Button type="button" variant="ghost" onClick={() => setMatchChatUrl(null)}>
                  {t("common.close")}
                </Button>
              </div>
            </Card>
          </div>
        ) : null}

        {waiting > 0 ? (
          <Card className="surface surface--inset" style={{ marginBottom: 14, padding: 14 }}>
            <div className="body" style={{ margin: 0, fontWeight: 600 }}>
              {t("likes.page.banner", { count: waiting })}
            </div>
          </Card>
        ) : null}

        {!premium ? (
          <div style={{ marginBottom: 14, display: "flex", justifyContent: "flex-start" }}>
            <Button
              type="button"
              variant="primary"
              onClick={() => {
                void trackAnalyticsEvent("paywall_clicked", { source: "likes", surface: "likes_screen_unlock_all_banner" });
                void trackAnalyticsEvent("paywall_shown", { surface: "likes_upgrade_modal" });
                setPaywallOpen(true);
              }}
            >
              {t("likes.page.seeWhoLikedYou")}
            </Button>
          </div>
        ) : null}

        {error ? (
          <Card className="surface" style={{ padding: 18 }}>
            <p className="body" style={{ margin: 0 }}>
              {error}
            </p>
            <div style={{ marginTop: 12 }}>
              <Button type="button" variant="primary" onClick={() => void load()}>
                {t("common.tryAgain")}
              </Button>
            </div>
          </Card>
        ) : null}

        {loading ? (
          <div className="likes-you-panel__grid" aria-busy>
            {[0, 1, 2, 3].map((i) => (
              <Card key={i} className="likes-you-card surface" style={{ minHeight: 280, opacity: 0.6 }}>
                <div aria-hidden />
              </Card>
            ))}
          </div>
        ) : !items.length ? (
          <Card className="surface" style={{ padding: 18 }}>
            <p className="body" style={{ margin: 0 }}>
              {t("likes.page.empty")}
            </p>
            <div style={{ marginTop: 12 }}>
              <Link className="btn btn-secondary" href="/discover">
                {t("likes.page.goDiscover")}
              </Link>
            </div>
          </Card>
        ) : (
          <div className="likes-you-panel__grid" aria-busy={false}>
            {items.map((row) => {
              const unblur = premium;
              const blurClass = unblur ? "" : "blur-full";
              const photo = row.photo_url ? row.photo_url : "";
              return (
                <Card key={row.user_id} className={`likes-you-card surface ${!photo ? "likes-you-card--no-photo" : ""} ${unblur ? "likes-you-card--premium" : "likes-you-card--locked"}`.trim()}>
                  <div className="likes-you-card__media">
                    {photo ? (
                      <SafeImg className={`likes-you-card__img ${blurClass}`.trim()} src={photo} alt="" loading="lazy" />
                    ) : (
                      <div className="likes-you-card__placeholder" aria-hidden />
                    )}
                    <div className="likes-you-card__overlay" />
                    {!unblur ? <div className="likes-you-card__blurGlass" aria-hidden /> : null}
                    <div className="likes-you-card__top">
                      <Badge>{t("likes.card.likedYou")}</Badge>
                    </div>
                    <div className="likes-you-card__bottom">
                      <div className="likes-you-card__name">{row.preview_name}</div>
                      <div className="likes-you-card__meta">{formatDist(row.distance)}</div>
                      <div className="likes-you-card__ctaRow" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                        <Button
                          type="button"
                          variant="primary"
                          className={premium ? undefined : "likes-you-card__revealPulse"}
                          onClick={() => void onReveal(row.user_id)}
                        >
                          {premium ? t("likes.page.reveal") : t("likes.page.seeWhoLikedYou")}
                        </Button>
                        <Button type="button" variant="ghost" onClick={() => void onHide(row.user_id)}>
                          {t("likes.page.hide")}
                        </Button>
                      </div>
                    </div>
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </section>
    </PageShell>
  );
}
