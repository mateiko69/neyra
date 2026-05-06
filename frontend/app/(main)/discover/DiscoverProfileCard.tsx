"use client";

import type { CSSProperties } from "react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { pickDiscoverReasons } from "../../../lib/aiSurfaceCopy";
import { buildDiscoverMicroHook, discoverReplySpeedTone } from "../../../lib/discover/microSignals";
import { genderBucketFromRaw } from "../../../lib/genderLabels";
import { fetchCompatibilityScoresBatch, type CompatibilityScore } from "../../../lib/compatibility/api";
import { photosFromList, resolveMediaUrl } from "../../../lib/media";
import { useT } from "../../components/i18n/I18nProvider";
import { VerifiedBadge } from "../../components/trust/VerifiedBadge";
import { PremiumBadge } from "../../components/trust/PremiumBadge";
import { Badge, Chip } from "../../components/ui";
import { DemoProfileImg } from "../../components/DemoProfileImg";
import { SafeImg } from "../../components/SafeImg";
import { isBundledDemoMainPhotoPath } from "../../../lib/demoProfiles";
import { resolveDemoProfilePhoto } from "../../../lib/resolvePhoto";
import { DiscoverInlineOpeners } from "./DiscoverInlineOpeners";

export type DiscoverCardData = {
  user_id: number;
  profile_id?: number | null;
  display_name?: string;
  age?: number | null;
  city?: string;
  distance_km?: number | null;
  last_active_at?: string | null;
  active_today?: boolean | null;
  bio?: string;
  photo_urls?: string[] | string;
  verified?: boolean;
  interests?: string[];
  top_reasons?: string[];
  compatibility_score?: number | null;
  warning_flags?: string[];
  ai_match?: boolean;
  visual_compatibility?: number | null;
  trusted?: "low" | "medium" | "high";
  is_verified?: boolean;
  verification_badge_visible?: boolean;
  is_premium?: boolean;
  premium_until?: string | null;
  is_demo_profile?: boolean;
  /** Premium AI showcase feed — no verification chrome; strict bundled photos. */
  demo_premium_showcase?: boolean;
  demo_personality_type?: string | null;
  demo_label?: string | null;
  demo_disclaimer?: string | null;
  gender?: string;
  /** Server: candidate already liked the viewer (mutual-interest signal). */
  they_liked_you?: boolean;
  /** Variable dopamine cue from feed (not every load). */
  variable_reward?: "spark_match" | "quality_spotlight" | "lucky_pick" | null;
  variable_reward_delay_ms?: number | null;
};

type Props = {
  card: DiscoverCardData;
  planTier?: "free" | "premium" | "premium_plus";
  viewerProfileId?: number | null;
  disabled: boolean;
  exiting: null | { liked: boolean };
  /** Brief pulse after onboarding to draw attention to the first profile. */
  highlightEntry?: boolean;
  /** Short UI flash after like / super-like (<300ms), driven by parent. */
  interactionFlash?: null | "like" | "super";
  onLike: () => void;
  /** Sends a like with `super_like` analytics flag (star control). */
  onSuperLike?: () => void;
  onPass: () => void;
  onIgnore: () => void;
  onPeek: () => void;
  /** Primary photo failed twice — parent removes card from deck. */
  onMediaFatal?: () => void;
};

const SWIPE_COMMIT_PX = 96;
const DRAG_ROT = 0.065;

function DiscoverProfileCardInner({
  card,
  planTier = "free",
  viewerProfileId = null,
  disabled,
  exiting,
  highlightEntry = false,
  interactionFlash = null,
  onLike,
  onSuperLike,
  onPass,
  onIgnore,
  onPeek,
  onMediaFatal,
}: Props) {
  const { t } = useT("DiscoverProfileCard");
  const photos = useMemo(
    () =>
      photosFromList(card.photo_urls)
        .map((raw) => resolveMediaUrl(String(raw || "").trim()))
        .filter(Boolean),
    [card.photo_urls],
  );
  const [photoIdx, setPhotoIdx] = useState(0);
  const [dragX, setDragX] = useState(0);
  const [pointerActive, setPointerActive] = useState(false);
  const dragStart = useRef<{ x: number; y: number } | null>(null);
  const moved = useRef(false);
  const draggingRef = useRef(false);
  const swipeSurfaceRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setPhotoIdx(0);
    setDragX(0);
  }, [card.user_id]);

  const safeIdx = photos.length ? Math.min(photoIdx, photos.length - 1) : 0;

  const goPhoto = useCallback(
    (delta: number) => {
      if (photos.length < 2 || disabled || exiting) return;
      setPhotoIdx((index) => (index + delta + photos.length) % photos.length);
    },
    [photos.length, disabled, exiting],
  );

  const onDotClick = useCallback(
    (index: number) => {
      if (disabled || exiting) return;
      setPhotoIdx(index);
    },
    [disabled, exiting],
  );

  const onSwipePointerDown = useCallback(
    (event: React.PointerEvent) => {
      if (disabled || exiting) return;
      if (event.button !== 0) return;
      const element = event.currentTarget as HTMLElement;
      element.setPointerCapture(event.pointerId);
      draggingRef.current = true;
      moved.current = false;
      dragStart.current = { x: event.clientX, y: event.clientY };
      setPointerActive(true);
    },
    [disabled, exiting],
  );

  const onSwipePointerMove = useCallback(
    (event: React.PointerEvent) => {
      if (!draggingRef.current || !dragStart.current || disabled || exiting) return;
      const dx = event.clientX - dragStart.current.x;
      const dy = event.clientY - dragStart.current.y;
      if (Math.abs(dx) > 8 || Math.abs(dy) > 8) moved.current = true;
      if (Math.abs(dx) > Math.abs(dy) * 0.5) setDragX(dx);
    },
    [disabled, exiting],
  );

  const onSwipePointerUp = useCallback(
    (event: React.PointerEvent) => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      setPointerActive(false);
      const start = dragStart.current;
      dragStart.current = null;
      const dx = start ? event.clientX - start.x : 0;

      let committed = false;
      if (!disabled && !exiting) {
        if (dx > SWIPE_COMMIT_PX) {
          committed = true;
          onLike();
        } else if (dx < -SWIPE_COMMIT_PX) {
          committed = true;
          onPass();
        } else if (!moved.current && photos.length > 1 && swipeSurfaceRef.current) {
          const rect = swipeSurfaceRef.current.getBoundingClientRect();
          const x = event.clientX - rect.left;
          if (x < rect.width * 0.22) goPhoto(-1);
          else if (x > rect.width * 0.78) goPhoto(1);
        }
      }
      setDragX(0);
      if (!committed) moved.current = false;
    },
    [disabled, exiting, onLike, onPass, photos.length, goPhoto],
  );

  const onSwipePointerCancel = useCallback(() => {
    draggingRef.current = false;
    setPointerActive(false);
    dragStart.current = null;
    setDragX(0);
    moved.current = false;
  }, []);

  const likeHint = exiting?.liked ? 1 : Math.min(1, Math.max(0, (dragX - 28) / 100));
  const passHint = exiting && !exiting.liked ? 1 : Math.min(1, Math.max(0, (-dragX - 28) / 100));
  const exitClass = exiting ? (exiting.liked ? "discover-card--exit-like" : "discover-card--exit-pass") : "";
  const rot = dragX * DRAG_ROT;

  const name = card.display_name || t("discover.card.profileFallback");
  const age = card.age != null ? String(card.age) : t("discover.card.ageFallback");
  const city = card.city || "";
  const distKmRaw = (card as any)?.distance_km ?? (card as any)?.distanceKm ?? null;
  const distKm = distKmRaw != null && Number.isFinite(Number(distKmRaw)) ? Math.max(0, Math.round(Number(distKmRaw))) : null;
  const activeToday =
    Boolean((card as any)?.active_today) ||
    (() => {
      const ts = String((card as any)?.last_active_at || "").trim();
      if (!ts) return false;
      const ms = Date.parse(ts);
      if (!Number.isFinite(ms)) return false;
      return Date.now() - ms <= 24 * 60 * 60 * 1000;
    })();
  const surfaceReasons = useMemo(() => pickDiscoverReasons(card.top_reasons, t, 2), [card.top_reasons, t]);

  const [aiLoading, setAiLoading] = useState(false);
  const [aiCompat, setAiCompat] = useState<CompatibilityScore | null>(null);

  useEffect(() => {
    let cancelled = false;
    setAiCompat(null);
    if (card.demo_premium_showcase) {
      setAiLoading(false);
      return;
    }
    const vp = viewerProfileId != null ? Math.trunc(Number(viewerProfileId)) : 0;
    const cp = card.profile_id != null ? Math.trunc(Number(card.profile_id)) : 0;
    if (!Number.isFinite(vp) || vp < 1 || !Number.isFinite(cp) || cp < 1) return;
    setAiLoading(true);
    void fetchCompatibilityScoresBatch({ viewerProfileId: vp, candidateProfileIds: [cp] })
      .then((map) => {
        if (cancelled) return;
        setAiCompat(map.get(cp) || null);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setAiLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [card.profile_id, card.user_id, card.demo_premium_showcase, viewerProfileId]);

  const aiBlock = useMemo(() => {
    const fallbackScore = Number.isFinite(Number(card.compatibility_score)) ? Math.max(0, Math.min(100, Math.round(Number(card.compatibility_score)))) : 72;
    const score = aiCompat ? Math.max(0, Math.min(100, Math.round(aiCompat.score))) : fallbackScore;
    const available = Boolean(aiCompat?.available);
    const reasons =
      aiCompat && Array.isArray(aiCompat.reasons) && aiCompat.reasons.length
        ? aiCompat.reasons.slice(0, 3)
        : [t("discover.card.aiReasonFallback1"), t("discover.card.aiReasonFallback2"), t("discover.card.aiReasonFallback3")];
    const name = String(card.display_name || "").trim() || t("discover.card.aiNameFallback");
    const city = String(card.city || "").trim();
    const opener = city ? t("discover.card.aiOpenerWithCity", { city }) : t("discover.card.aiOpenerNoCity");
    return {
      title: t("discover.card.aiMatchTitle"),
      score,
      status: aiLoading ? t("discover.card.aiLoadingStatus") : available ? null : t("discover.card.aiPrepStatus"),
      reasons,
      opener: `“${opener.split('"').join("").trim()}”`,
    };
  }, [aiCompat, aiLoading, card.city, card.compatibility_score, card.display_name, t]);

  const displayMatchPct = aiBlock.score;
  const microHook = useMemo(() => {
    const raw = buildDiscoverMicroHook(card, surfaceReasons);
    return raw || t("discover.card.microHook.fallback");
  }, [card, surfaceReasons, t]);

  const replySpeedTone = useMemo(() => discoverReplySpeedTone(card), [card.active_today, card.last_active_at]);

  const isVerified = Boolean(card.is_verified);
  const demoPremiumShowcase = Boolean(card.demo_premium_showcase);
  const showVerifiedBadge = isVerified && card.verification_badge_visible !== false && !demoPremiumShowcase;
  const isPremium = Boolean(card.is_premium);
  const isDemoProfile = Boolean(card.is_demo_profile);
  const demoPersonality = String(card.demo_personality_type || "").trim() || "calm";
  const useStrictDemoPhoto =
    demoPremiumShowcase || (isDemoProfile && isBundledDemoMainPhotoPath(String(photos[0] || "")));

  const vrTag = card.variable_reward ?? null;
  const vrDelay = card.variable_reward_delay_ms != null && Number.isFinite(Number(card.variable_reward_delay_ms)) ? Math.max(0, Math.trunc(Number(card.variable_reward_delay_ms))) : 0;
  const [showVariableReward, setShowVariableReward] = useState(false);

  useEffect(() => {
    setShowVariableReward(false);
    if (!vrTag) return;
    const tid = window.setTimeout(() => setShowVariableReward(true), vrDelay);
    return () => window.clearTimeout(tid);
  }, [card.user_id, vrTag, vrDelay]);

  const variableRewardLabel = useMemo(() => {
    if (!vrTag) return "";
    if (vrTag === "spark_match") return t("discover.variableReward.spark_match");
    if (vrTag === "quality_spotlight") return t("discover.variableReward.quality_spotlight");
    return t("discover.variableReward.lucky_pick");
  }, [vrTag, t]);

  const genderBucket = genderBucketFromRaw(card.gender);
  const genderLabel =
    genderBucket === "male"
      ? t("discover.card.genderBadgeMale")
      : genderBucket === "female"
        ? t("discover.card.genderBadgeFemale")
        : genderBucket === "nonbinary"
          ? t("profile.gender.nonbinary")
          : null;

  const tiltStyle: CSSProperties = exiting
    ? {}
    : {
        transform: `translateX(${dragX}px) rotate(${rot}deg)`,
        transition: pointerActive ? "none" : "transform 0.34s cubic-bezier(0.34, 1.15, 0.42, 1)",
      };

  return (
    <article
      data-testid="discover-card"
      className={`discover-card surface discover-card--front ${exitClass} ${pointerActive ? "discover-card--dragging" : ""} ${showVerifiedBadge ? "trust-verified" : ""} ${isPremium ? "discover-card--premium" : ""} ${highlightEntry ? "discover-card--entry-highlight" : ""} ${interactionFlash === "super" ? "discover-card--super-flash" : ""}`.trim()}
      aria-label={
        city
          ? t("discover.card.aria.summaryWithCity", { name, age, city })
          : t("discover.card.aria.summary", { name, age })
      }
    >
      <div className="discover-card__tilt" style={tiltStyle}>
        <div
          ref={swipeSurfaceRef}
          className="discover-card__swipe-surface"
          onPointerDown={onSwipePointerDown}
          onPointerMove={onSwipePointerMove}
          onPointerUp={onSwipePointerUp}
          onPointerCancel={onSwipePointerCancel}
          role="group"
          aria-label={photos.length > 1 ? t("discover.card.aria.photos") : t("discover.card.aria.profile")}
        >
          <div className="discover-card__media discover-card__media--rail">
            <div className="discover-card__photo-rail" style={{ transform: `translateX(-${safeIdx * 100}%)` }}>
              {photos.length ? (
                photos.map((url, index) => (
                  <div key={`${card.user_id}-p-${index}`} className="discover-card__photo-slide">
                    {useStrictDemoPhoto && index === 0 ? (
                      <DemoProfileImg
                        className="discover-card__img"
                        loading={index === 0 ? "eager" : "lazy"}
                        src={url}
                        alt={index === 0 ? name : t("discover.card.photoAlt", { name, index: index + 1 })}
                        photoTestId={index === 0 ? "discover-photo" : undefined}
                        onFatalError={onMediaFatal}
                      />
                    ) : (
                      <SafeImg
                        className="discover-card__img"
                        loading={index === 0 ? "eager" : "lazy"}
                        src={url}
                        alt={index === 0 ? name : t("discover.card.photoAlt", { name, index: index + 1 })}
                        photoTestId={index === 0 ? "discover-photo" : undefined}
                      />
                    )}
                  </div>
                ))
              ) : (
                <div className="discover-card__photo-slide">
                  {(() => {
                    const fallbackSrc = resolveDemoProfilePhoto(card);
                    return useStrictDemoPhoto && isDemoProfile ? (
                      <DemoProfileImg
                        className="discover-card__img"
                        loading="eager"
                        src={fallbackSrc}
                        alt={name}
                        photoTestId="discover-photo"
                        onFatalError={onMediaFatal}
                      />
                    ) : (
                      <SafeImg
                        className="discover-card__img"
                        loading="eager"
                        src={fallbackSrc}
                        alt={name}
                        photoTestId="discover-photo"
                      />
                    );
                  })()}
                </div>
              )}
            </div>
            <div className="discover-card__hover-glow" aria-hidden />
            <div className="discover-card__shade discover-card__shade--vignette" aria-hidden />
            {showVariableReward && variableRewardLabel ? (
              <div className="discover-card__variable-reward" aria-hidden>
                {variableRewardLabel}
              </div>
            ) : null}
            {isDemoProfile && !demoPremiumShowcase ? (
              <div
                className="discover-card__demo-corner"
                style={{
                  position: "absolute",
                  top: 14,
                  right: 14,
                  zIndex: 6,
                  pointerEvents: "none",
                }}
              >
                <Badge tone="premium">{t("demo.badge")}</Badge>
              </div>
            ) : null}
            <div
              className={`discover-card__micro-top${isDemoProfile ? " discover-card__micro-top--demo discover-card__micro-top--ribbon" : ""}`.trim()}
            >
              <div className="discover-card__micro-top-left">
                <div
                  className="discover-card__micro-pill discover-card__micro-pill--match"
                  aria-label={t("discover.card.microSignals.matchAria", { score: displayMatchPct })}
                >
                  <span className="discover-card__micro-pill__value">{displayMatchPct}</span>
                  <span className="discover-card__micro-pill__suffix" aria-hidden>
                    %
                  </span>
                </div>
                {genderLabel ? (
                  <div className="discover-card__micro-gender">
                    <Badge>{genderLabel}</Badge>
                  </div>
                ) : null}
              </div>
              <div className="discover-card__micro-top-right">
                {replySpeedTone ? (
                  <div
                    className={`discover-card__micro-pill discover-card__micro-pill--reply discover-card__micro-pill--reply-${replySpeedTone}`}
                  >
                    {replySpeedTone === "fast" ? t("discover.card.replySpeed.fast") : t("discover.card.replySpeed.slow")}
                  </div>
                ) : null}
              </div>
            </div>
            {exiting && exiting.liked ? (
              <div
                className="discover-card__feedback-toast"
                style={{
                  position: "absolute",
                  left: 14,
                  right: 14,
                  top: 68,
                  zIndex: 5,
                  display: "flex",
                  justifyContent: "center",
                  pointerEvents: "none",
                }}
                aria-live="polite"
              >
                <div
                  style={{
                    padding: "10px 12px",
                    borderRadius: 999,
                    border: "1px solid rgba(255,255,255,0.18)",
                    background: "rgba(120,255,180,0.18)",
                    backdropFilter: "blur(10px)",
                    fontWeight: 900,
                  }}
                >
                  {t("discover.swipe.likeToast")}
                </div>
              </div>
            ) : null}
            {showVerifiedBadge ? (
              <div
                className="trust-hint"
                style={{ position: "absolute", left: 14, right: 14, bottom: 14, pointerEvents: "none" }}
              >
                {t("trust.discover.verifiedRespondHint")}
              </div>
            ) : null}
            {photos.length > 1 ? (
              <div className="discover-card__dots" role="tablist" aria-label={t("discover.card.photosLabel")}>
                {photos.map((_, index) => (
                  <button
                    key={index}
                    type="button"
                    role="tab"
                    aria-selected={index === safeIdx}
                    className={`discover-card__dot ${index === safeIdx ? "discover-card__dot--active" : ""}`}
                    onPointerDown={(event) => event.stopPropagation()}
                    onClick={(event) => {
                      event.stopPropagation();
                      onDotClick(index);
                    }}
                    disabled={disabled || !!exiting}
                  />
                ))}
              </div>
            ) : null}
            <div
              className="discover-card__stamp discover-card__stamp--like"
              style={{
                opacity: likeHint,
                transform: `translate(-50%, -50%) rotate(-16deg) scale(${0.88 + likeHint * 0.14})`,
              }}
              aria-hidden
            >
              <span>{t("discover.card.like")}</span>
            </div>
            <div
              className="discover-card__stamp discover-card__stamp--pass"
              style={{
                opacity: passHint,
                transform: `translate(-50%, -50%) rotate(14deg) scale(${0.88 + passHint * 0.14})`,
              }}
              aria-hidden
            >
              <span>{t("discover.card.nope")}</span>
            </div>
            <div className="discover-card__swipe-hint" aria-hidden>
              {photos.length > 1 ? t("discover.card.hint.photos") : t("discover.card.hint.actions")}
            </div>
            {interactionFlash === "like" ? (
              <div className="discover-card__feedback-like" aria-live="polite">
                <div className="discover-card__feedback-like-hearts" aria-hidden>
                  <span className="discover-card__feedback-heart">❤</span>
                </div>
                <p className="discover-card__feedback-like-text">{t("discover.feedback.likeMicro")}</p>
              </div>
            ) : null}
            <div className="discover-card__meta">
              <div className="discover-card__meta-inner">
                <div className="discover-card__micro-bottom">
                  {distKm != null && distKm > 0 ? (
                    <span className="discover-card__micro-dist">{t("discover.card.microSignals.distApprox", { km: distKm })}</span>
                  ) : null}
                  <p className="discover-card__micro-hook" title={microHook} aria-label={t("discover.card.microSignals.hookAria")}>
                    {microHook}
                  </p>
                </div>
                <h2 className="discover-card__name">
                  <span className="discover-card__name-text">{name}</span>
                  {showVerifiedBadge ? <VerifiedBadge title={t("trust.verified.tooltip")} /> : null}
                  {isPremium ? <PremiumBadge title={t("premium.badge")} /> : null}
                  <span className="discover-card__name-sep" aria-hidden>
                    ,
                  </span>
                  <span className="discover-card__age">{age}</span>
                </h2>
                {city ? (
                  <div className="discover-card__city-row">
                    <svg
                      className="discover-card__city-icon"
                      width="16"
                      height="16"
                      viewBox="0 0 24 24"
                      fill="none"
                      aria-hidden
                    >
                      <path
                        d="M12 21s7-5.06 7-11a7 7 0 1 0-14 0c0 5.94 7 11 7 11Z"
                        stroke="currentColor"
                        strokeWidth="1.8"
                        strokeLinejoin="round"
                      />
                      <circle cx="12" cy="10" r="2.25" fill="currentColor" />
                    </svg>
                    <span>{city}</span>
                  </div>
                ) : null}
                {activeToday ? (
                  <div className="discover-card__city-row" style={{ marginTop: 4, opacity: 0.92, fontWeight: 750 }}>
                    {t("discover.card.activeToday")}
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </div>

        <div className="discover-card__body">
          {isDemoProfile ? (
            <div
              className="caption"
              style={{
                marginBottom: 10,
                padding: "10px 12px",
                borderRadius: 12,
                border: "1px solid rgba(180, 120, 255, 0.35)",
                background: "rgba(180, 120, 255, 0.12)",
                fontWeight: 650,
                lineHeight: 1.45,
              }}
              role="status"
            >
              {demoPremiumShowcase ? t("demo.showcase.notice") : t("demo.notice")}
            </div>
          ) : null}
          {isDemoProfile ? (
            <div className="discover-card__personality-pill">
              <Badge tone="premium">
                {t(
                  ["playful", "deep", "calm", "teasing"].includes(demoPersonality)
                    ? (`demo.personality.${demoPersonality}` as const)
                    : "demo.personality.calm",
                )}
              </Badge>
            </div>
          ) : null}
          <div
            style={{
              marginBottom: 10,
              padding: "10px 12px",
              borderRadius: 14,
              border: "1px solid rgba(180, 120, 255, 0.22)",
              background: "rgba(180, 120, 255, 0.07)",
              display: "grid",
              gap: 6,
            }}
            aria-label={t("discover.card.aiMatchAria")}
          >
            <div style={{ fontWeight: 900 }}>{aiBlock.title} · {aiBlock.score}%</div>
            {aiBlock.status ? <div className="caption" style={{ opacity: 0.85 }}>{aiBlock.status}</div> : null}
            <div className="caption" style={{ opacity: 0.92 }}>
              {aiBlock.reasons.slice(0, 3).map((r) => `• ${r}`).join("  ")}
            </div>
            <div className="caption" style={{ opacity: 0.92 }}>
              <strong>{t("discover.card.aiOpener")}</strong> {aiBlock.opener}
            </div>
          </div>
          <p
            className="discover-card__bio body muted"
            style={
              {
                display: "-webkit-box",
                WebkitLineClamp: 3,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
              } as CSSProperties
            }
          >
            {card.bio || t("discover.card.noBio")}
          </p>
          <button type="button" className="discover-detail-link" onClick={onPeek}>
            {t("discover.card.fullProfile")}
          </button>
          {disabled || exiting ? null : <DiscoverInlineOpeners card={card} />}
          <div className="discover-card__chips">
            {(card.interests || []).slice(0, 8).map((interest: string) => (
              <Chip key={interest}>{interest}</Chip>
            ))}
          </div>
        </div>
      </div>

      {aiBlock?.opener ? (
        <div style={{ marginTop: 10 }}>
          <button type="button" className="btn btn-primary" onClick={onPeek}>
            ✨ {t("discover.ai.startWithAI")}
          </button>
        </div>
      ) : null}
    </article>
  );
}

export const DiscoverProfileCard = memo(DiscoverProfileCardInner);
