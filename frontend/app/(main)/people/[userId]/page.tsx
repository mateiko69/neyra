"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { setChatThreadHeaderSeed } from "../../../../lib/chat/threadHeaderSeed";
import { apiFetch, formatApiError, getToken, invalidateApiGetCache } from "../../../../lib/api";
import { AI_DEBUG_ENABLED } from "../../../../lib/aiDebug";
import { resolveAiTier } from "../../../../lib/chat/aiTier";
import { i18nKey, rawI18nText, resolveI18nText, type I18nText } from "../../../../lib/i18n/message";
import { apiFailureToI18nText } from "../../../../lib/i18n/translateApiUserMessage";
import { queueNextPageToast } from "../../../../lib/nextPageToast";
import { blockUser, ignoreUser, reportUser, type ReportCategory } from "../../../../lib/safety/api";
import { fetchCompatibilityScore, type CompatibilityScore } from "../../../../lib/compatibility/api";
import { trackAnalyticsEvent } from "../../../../lib/analytics";
import { fetchProfileTrust, type ProfileTrust } from "../../../../lib/trust/api";
import { trackPremiumPlusHookClicked, trackPremiumPlusHookSeen } from "../../../../lib/premiumPlusHooks";
import { buildSubscriptionHref, getPremiumPlusHookVariant, maybeEmitHookConverted, trackPremiumPlusHookVariant } from "../../../../lib/premiumPlusHookOptimization";
import { AiDebugPill } from "../../../components/AiDebugPill";
import { EmptyState } from "../../../components/EmptyState";
import { useT } from "../../../components/i18n/I18nProvider";
import { PageHeader } from "../../../components/PageHeader";
import { PageShell } from "../../../components/PageShell";
import { SafeImg } from "../../../components/SafeImg";
import { PremiumBadge } from "../../../components/trust/PremiumBadge";
import { VerifiedBadge } from "../../../components/trust/VerifiedBadge";
import { Badge, Button, Card, Chip, Skeleton, Toast } from "../../../components/ui";
import { resolvePhoto } from "../../../../lib/resolvePhoto";

type PartnerPublic = {
  user_id: number;
  display_name: string;
  age: number | null;
  city: string;
  bio: string;
  interests: string[];
  lifestyle_tags: string[];
  photo_urls: string[];
  relationship_goal: string;
  verified?: boolean;
  is_verified?: boolean;
  verification_level?: string;
  verification_badge_visible?: boolean;
  is_premium?: boolean;
  premium_until?: string | null;
  is_demo_profile?: boolean;
  demo_label?: string | null;
  demo_disclaimer?: string | null;
};

const REPORT_REASONS: ReportCategory[] = [
  "harassment",
  "spam",
  "hate",
  "nudity",
  "scam",
  "impersonation",
  "minor",
  "other",
];

function partnerIdFromParams(raw: string | undefined): number | null {
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed < 1) return null;
  return Math.trunc(parsed);
}

function ReportReasonModal({
  open,
  reason,
  busy,
  onSelect,
  onClose,
  onSubmit,
}: {
  open: boolean;
  reason: ReportCategory;
  busy: boolean;
  onSelect: (value: ReportCategory) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const { t } = useT("PersonReportDialog");

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose, open]);

  if (!open) return null;

  return (
    <div
      className="peek-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="report-user-title"
      onClick={busy ? undefined : onClose}
    >
      <Card className="surface peek-modal-card" onClick={(event) => event.stopPropagation()}>
        <div className="section-label">{t("people.report.eyebrow")}</div>
        <div id="report-user-title" className="h2" style={{ fontSize: 24, fontWeight: 850, letterSpacing: "-0.04em" }}>
          {t("people.report.title")}
        </div>
        <p className="body muted" style={{ marginTop: 10 }}>
          {t("people.report.description")}
        </p>

        <div style={{ display: "grid", gap: 10, marginTop: 18 }}>
          {REPORT_REASONS.map((option) => (
            <button
              key={option}
              type="button"
              className={option === reason ? "btn btn-secondary" : "btn btn-ghost"}
              style={{ justifyContent: "flex-start", textTransform: "capitalize" }}
              onClick={() => onSelect(option)}
              disabled={busy}
            >
              {t(`reportReason.${option}`)}
            </button>
          ))}
        </div>

        <div className="match-actions-row" style={{ marginTop: 18 }}>
          <Button type="button" variant="ghost" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button type="button" variant="primary" onClick={onSubmit} disabled={busy}>
            {busy ? t("common.sending") : t("people.report.send")}
          </Button>
        </div>
      </Card>
    </div>
  );
}

export default function PartnerProfilePage() {
  const router = useRouter();
  const { t } = useT("PersonPage");
  const params = useParams<{ userId: string }>();
  const userId = partnerIdFromParams(params.userId) ?? NaN;

  const [data, setData] = useState<PartnerPublic | null>(null);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<I18nText>(null);
  const [actionBusy, setActionBusy] = useState<"block" | "ignore" | "report" | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportReason, setReportReason] = useState<ReportCategory>("harassment");
  const [ignored, setIgnored] = useState(false);
  const [blockedRedirecting, setBlockedRedirecting] = useState(false);
  const [planCode, setPlanCode] = useState<string>("");
  const [viewerIsPremium, setViewerIsPremium] = useState(false);
  const [viewerProfileId, setViewerProfileId] = useState<number | null>(null);
  const [compat, setCompat] = useState<CompatibilityScore | null>(null);
  const compatTrackedRef = useRef(false);
  const [trust, setTrust] = useState<ProfileTrust | null>(null);
  const trustSeenRef = useRef(false);
  const loadGenRef = useRef(0);

  const aiTier = resolveAiTier({ isPremium: viewerIsPremium, planCode });
  useEffect(() => {
    void maybeEmitHookConverted(aiTier);
  }, [aiTier]);

  useEffect(() => {
    if (!getToken()) return;
    let cancelled = false;
    void apiFetch("/auth/me", { metaReason: "people-viewer", skipThrottle: true })
      .then((me) => {
        if (cancelled) return;
        setViewerIsPremium(Boolean(me && typeof me === "object" ? (me as any).is_premium ?? (me as any).isPremium : false));
      })
      .catch(() => {});
    void apiFetch("/profiles/me", { metaReason: "people-viewer-profile", skipThrottle: true })
      .then((p) => {
        if (cancelled) return;
        const id = Math.trunc(Number(p && typeof p === "object" ? (p as any).id : 0));
        setViewerProfileId(Number.isFinite(id) && id > 0 ? id : null);
      })
      .catch(() => {});
    void apiFetch("/subscriptions/me", { metaReason: "people-plan", skipThrottle: true })
      .then((s) => {
        if (cancelled) return;
        const code = String((s && typeof s === "object" ? (s as any).plan_code || (s as any).plan : "") || "");
        setPlanCode(code);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!viewerProfileId) return;
    if (!data) return;
    if (aiTier === "free") return;
    let cancelled = false;
    void fetchCompatibilityScore({ viewerProfileId, candidateProfileId: data.user_id })
      .then((res) => {
        if (cancelled) return;
        setCompat(res);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [aiTier, data, viewerProfileId]);

  useEffect(() => {
    if (!data) return;
    if (data.is_demo_profile) {
      setTrust(null);
      return;
    }
    if (aiTier === "free") return;
    let cancelled = false;
    void fetchProfileTrust({ userId: data.user_id })
      .then((res) => {
        if (cancelled) return;
        setTrust(res);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [aiTier, data]);

  useEffect(() => {
    if (aiTier === "free") return;
    if (!trust) return;
    if (trustSeenRef.current) return;
    trustSeenRef.current = true;
    void trackAnalyticsEvent("trust_badge_seen", {
      plan_tier: aiTier,
      trust_level: trust.trust_level,
      is_verified: trust.is_verified,
      surface: "profile_detail",
    });
  }, [aiTier, trust]);

  useEffect(() => {
    if (aiTier === "free") return;
    if (!compat || !compat.available) return;
    if (compatTrackedRef.current) return;
    compatTrackedRef.current = true;
    const scoreBucket = compat.score >= 80 ? "high" : compat.score >= 55 ? "medium" : "low";
    void trackAnalyticsEvent("ai_compatibility_detail_opened", {
      plan_tier: aiTier,
      score_bucket: scoreBucket,
      has_visual_score: compat.visual_score != null,
      has_vibe_score: compat.vibe_score != null,
    });
  }, [aiTier, compat]);

  useEffect(() => {
    if (!Number.isFinite(userId)) {
      setLoading(false);
      return;
    }
    if (!getToken()) {
      router.replace("/login");
      return;
    }

    const loadGen = (loadGenRef.current += 1);
    let cancelled = false;

    void (async () => {
      setLoading(true);
      try {
        const profile = await apiFetch(`/profiles/partner/${userId}`, {
          metaReason: `partner-profile-${userId}`,
        });
        if (!cancelled && loadGenRef.current === loadGen) {
          setData(profile as PartnerPublic);
          setIgnored(false);
        }
      } catch (errorValue: unknown) {
        if (!cancelled && loadGenRef.current === loadGen) {
          setData(null);
          setToast(apiFailureToI18nText(errorValue, t, "people.errors.loadPartner", formatApiError));
        }
      } finally {
        if (!cancelled && loadGenRef.current === loadGen) {
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only reload on route user change
  }, [userId]);

  function invalidateSafetyCaches(targetUserId: number) {
    invalidateApiGetCache("/matches");
    invalidateApiGetCache("/messages/conversations");
    invalidateApiGetCache("/discover/feed");
    invalidateApiGetCache("/nav/badges");
    invalidateApiGetCache(`/messages/${targetUserId}`);
    invalidateApiGetCache(`/profiles/partner/${targetUserId}`);
  }

  async function handleBlockUser() {
    if (!data || actionBusy) return;
    const confirmed =
      typeof window === "undefined" ? true : window.confirm(t("people.safety.confirmBlock"));
    if (!confirmed) return;

    setActionBusy("block");
    setBlockedRedirecting(true);

    try {
      await blockUser(data.user_id);
      invalidateSafetyCaches(data.user_id);
      queueNextPageToast(i18nKey("people.safety.blockedToast"));
      router.replace("/matches");
    } catch (errorValue: unknown) {
      setBlockedRedirecting(false);
      setToast(apiFailureToI18nText(errorValue, t, "people.errors.safetyAction", formatApiError));
    } finally {
      setActionBusy(null);
    }
  }

  async function handleIgnoreUser() {
    if (!data || actionBusy || ignored) return;
    setActionBusy("ignore");
    try {
      await ignoreUser(data.user_id);
      invalidateApiGetCache("/discover/feed");
      setIgnored(true);
      setToast(i18nKey("people.safety.ignoredToast"));
    } catch (errorValue: unknown) {
      setToast(apiFailureToI18nText(errorValue, t, "people.errors.safetyAction", formatApiError));
    } finally {
      setActionBusy(null);
    }
  }

  async function handleSubmitReport() {
    if (!data || actionBusy) return;
    setActionBusy("report");
    try {
      await reportUser(data.user_id, reportReason);
      setReportOpen(false);
      setToast(i18nKey("people.report.sent"));
    } catch (errorValue: unknown) {
      setToast(apiFailureToI18nText(errorValue, t, "people.errors.safetyAction", formatApiError));
    } finally {
      setActionBusy(null);
    }
  }

  if (!Number.isFinite(userId)) {
    return (
      <PageShell>
        <Card className="surface">
          <EmptyState
            kicker={t("people.invalid.kicker")}
            title={t("people.invalid.title")}
            description={t("people.invalid.description")}
            spacious
          >
            <Link href="/matches" className="btn btn-primary">
              {t("navigation.matches")}
            </Link>
            <Link href="/chat" className="btn btn-ghost">
              {t("chat.inbox.title")}
            </Link>
          </EmptyState>
        </Card>
      </PageShell>
    );
  }

  if (loading) {
    return (
      <PageShell>
        <Skeleton style={{ height: 56, borderRadius: 14 }} />
        <Card className="surface">
          <Skeleton style={{ height: 240, borderRadius: 20 }} />
          <div style={{ height: 16 }} />
          <Skeleton style={{ height: 28, width: "60%", borderRadius: 10 }} />
        </Card>
      </PageShell>
    );
  }

  if (!data) {
    return (
      <>
        <PageShell>
          <Card className="surface">
            <EmptyState
              kicker={t("people.unavailable.kicker")}
              title={t("people.unavailable.title")}
              description={t("people.unavailable.description")}
              spacious
            >
              <Link href="/matches" className="btn btn-secondary">
                {t("navigation.matches")}
              </Link>
              <Link href={`/chat/${userId}`} className="btn btn-ghost">
                {t("people.actions.openChat")}
              </Link>
            </EmptyState>
          </Card>
        </PageShell>
        <Toast text={resolveI18nText(toast, t)} onClose={() => setToast(null)} />
      </>
    );
  }

  if (blockedRedirecting) {
    return (
      <>
        <PageShell>
          <Card className="surface">
            <EmptyState
              kicker={t("people.blocked.kicker")}
              title={t("people.blocked.title")}
              description={t("people.blocked.description")}
              spacious
            />
          </Card>
        </PageShell>
        <Toast text={resolveI18nText(toast, t)} onClose={() => setToast(null)} />
      </>
    );
  }

  const metaParts = [data.age != null && data.age > 0 ? `${data.age}` : null, data.city?.trim() || null].filter(Boolean);
  const meta = metaParts.join(" / ");
  const isDemoProfile = Boolean(data.is_demo_profile);
  const partnerVerified = Boolean(data.is_verified ?? data.verified);
  const showPartnerVerifiedBadge = partnerVerified && data.verification_badge_visible !== false;
  const partnerPremium = Boolean(data.is_premium);
  const trustHiddenReason =
    aiTier === "free"
      ? t("people.debug.trustHidden.requiresPremium")
      : !trust
        ? t("people.debug.trustHidden.noData")
        : null;
  const compatHiddenReason =
    aiTier === "free"
      ? t("people.debug.compatHidden.requiresPremium")
      : !compat
        ? t("people.debug.compatHidden.noData")
        : !compat.available
          ? t("people.debug.compatHidden.unavailable")
          : null;
  const compatPlusHiddenReason =
    aiTier === "premium" && compat && compat.available ? t("people.debug.compatPlusHidden.requiresPremiumPlus") : null;

  return (
    <>
      <PageShell>
        {isDemoProfile ? (
          <div
            role="status"
            style={{
              marginBottom: 16,
              padding: "12px 14px",
              borderRadius: 14,
              border: "1px solid rgba(180, 120, 255, 0.35)",
              background: "rgba(180, 120, 255, 0.12)",
              fontWeight: 650,
              lineHeight: 1.45,
              maxWidth: "72ch",
            }}
          >
            {t("demo.profile.label")}
          </div>
        ) : null}
        <PageHeader
          variant="hero"
          title={data.display_name}
          subtitle={meta || t("people.header.subtitle")}
          allowRawTitle
          allowRawSubtitle={Boolean(meta)}
          badge={
            isDemoProfile ? (
              <Badge tone="premium">{t("demo.badge")}</Badge>
            ) : (
              <span style={{ display: "inline-flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                {showPartnerVerifiedBadge ? <VerifiedBadge title={t("trust.verified.tooltip")} /> : null}
                {partnerPremium ? <PremiumBadge title={t("premium.badge")} /> : null}
                <Badge tone="streak">{t("people.header.badge")}</Badge>
              </span>
            )
          }
          status={t("people.header.status")}
          statusVariant="neutral"
          action={
            <>
              <Link
                href={`/chat/${data.user_id}`}
                className="btn btn-primary"
                onClick={() =>
                  setChatThreadHeaderSeed(data.user_id, {
                    displayName: data.display_name,
                    avatarUrl: resolvePhoto(data) || null,
                  })
                }
              >
                {t("people.actions.openChat")}
              </Link>
              <Link href="/matches" className="btn btn-ghost">
                {t("people.actions.allMatches")}
              </Link>
            </>
          }
        />

        <Card className={`surface ${partnerPremium ? "people-profile-card--premium" : ""}`.trim()}>
          {!isDemoProfile ? (
            <>
              <div className="section-label">{t("profile.trustStatus.title")}</div>
              <div className="body muted" style={{ marginTop: 8, marginBottom: 16, display: "grid", gap: 8 }}>
                <div>
                  <strong>{t("profile.trust.verified")}:</strong>{" "}
                  {partnerVerified ? t("profile.trustStatus.verifiedYes") : t("profile.trustStatus.verifiedNo")}
                </div>
                <div>
                  <strong>{t("premium.badge")}:</strong>{" "}
                  {partnerPremium ? t("profile.trustStatus.premiumYes") : t("profile.trustStatus.premiumNo")}
                </div>
              </div>
            </>
          ) : null}
          {data.photo_urls?.length ? (
            <div
              style={{
                display: "flex",
                gap: 12,
                overflowX: "auto",
                paddingBottom: 10,
                marginBottom: 20,
                scrollSnapType: "x mandatory",
              }}
            >
              {data.photo_urls.map((url, index) => (
                <SafeImg
                  key={`${index}-${url.slice(0, 32)}`}
                  src={url}
                  loading={index === 0 ? "eager" : "lazy"}
                  alt={t("people.photos.alt", { name: data.display_name, index: index + 1 })}
                  style={{
                    width: 200,
                    height: 260,
                    minWidth: 200,
                    borderRadius: "var(--r-xl)",
                    objectFit: "cover",
                    border: "1px solid rgba(255,255,255,0.12)",
                    scrollSnapAlign: "start",
                  }}
                />
              ))}
            </div>
          ) : (
            <div className="photo-upload-empty" style={{ marginBottom: 20 }}>
              <div className="photo-upload-empty-title">{t("people.photos.empty.title")}</div>
              <p className="photo-upload-empty-desc">{t("people.photos.empty.description")}</p>
            </div>
          )}

          <div className="section-label">{t("people.sections.lookingFor")}</div>
          <Chip>{t(`goals.${data.relationship_goal || "relationship"}`)}</Chip>

          {data.bio?.trim() ? (
            <>
              <div style={{ height: 20 }} />
              <div className="section-label">{t("people.sections.about")}</div>
              <div className="body" style={{ whiteSpace: "pre-wrap" }}>
                {data.bio.trim()}
              </div>
            </>
          ) : null}

          {AI_DEBUG_ENABLED ? (
            <div style={{ display: "grid", gap: 8, marginTop: 20 }}>
              <AiDebugPill label={trustHiddenReason} />
              <AiDebugPill label={compatHiddenReason} />
              <AiDebugPill label={compatPlusHiddenReason} />
            </div>
          ) : null}

          {aiTier !== "free" && trust && !isDemoProfile ? (
            <>
              <div style={{ height: 20 }} />
              <div className="section-label">{t("people.trust.title")}</div>
              <div className="body muted" style={{ display: "flex", alignItems: "center", gap: 10 }}>
                {trust.is_verified ? (
                  <span title={t("trust.verified.tooltip")}>✔ {t("people.trust.verified")}</span>
                ) : trust.trust_level === "high" ? (
                  <span>{t("people.trust.complete")}</span>
                ) : (
                  <span>{t("people.trust.building")}</span>
                )}
                <button
                  type="button"
                  className="btn btn-ghost"
                  style={{ padding: "6px 10px" }}
                  onClick={() => {
                    void trackAnalyticsEvent("trust_badge_clicked", {
                      plan_tier: aiTier,
                      trust_level: trust.trust_level,
                      is_verified: trust.is_verified,
                      surface: "profile_detail",
                    });
                  }}
                >
                  {t("people.trust.details")}
                </button>
              </div>
            </>
          ) : null}

          {aiTier !== "free" && compat && compat.available ? (
            <>
              <div style={{ height: 20 }} />
              <div className="section-label">{t("people.compatibility.title")}</div>
              <div className="body muted" style={{ opacity: 0.92 }}>
                {aiTier === "premium_plus"
                  ? t("people.compatibility.matchLine", { percent: compat.score })
                  : t("people.compatibility.insightLine")}
              </div>
              {(aiTier === "premium_plus" ? compat.reasons.slice(0, 3) : compat.reasons.slice(0, 1)).length ? (
                <ul className="body muted" style={{ marginTop: 10, paddingLeft: 18 }}>
                  {(aiTier === "premium_plus" ? compat.reasons.slice(0, 3) : compat.reasons.slice(0, 1)).map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              ) : null}
              {aiTier === "premium" ? (
                <div className="chat-ai-inline__upsell" style={{ marginTop: 12 }} aria-live="polite">
                  <div className="chat-ai-inline__upsell-text">{getPremiumPlusHookVariant("compatibility").text}</div>
                  <Link
                    href={buildSubscriptionHref("compatibility", getPremiumPlusHookVariant("compatibility").variant_id)}
                    className="chat-ai-inline__upgrade"
                    onClick={() => {
                      const v = getPremiumPlusHookVariant("compatibility");
                      void trackPremiumPlusHookVariant({
                        context: "compatibility",
                        plan_tier: aiTier,
                        variant_id: v.variant_id,
                        copy_id: v.copy_id,
                        surface: "profile_detail_compat",
                      });
                      void trackPremiumPlusHookSeen({
                        context: "compatibility",
                        plan_tier: aiTier,
                        surface: "profile_detail_compat",
                        variant_id: v.variant_id,
                        copy_id: v.copy_id,
                      });
                      void trackPremiumPlusHookClicked({
                        context: "compatibility",
                        plan_tier: aiTier,
                        surface: "profile_detail_compat",
                        variant_id: v.variant_id,
                        copy_id: v.copy_id,
                      });
                    }}
                  >
                    {t("common.upgrade")}
                  </Link>
                </div>
              ) : null}
            </>
          ) : null}

          {data.interests?.length ? (
            <>
              <div style={{ height: 20 }} />
              <div className="section-label">{t("people.sections.interests")}</div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {data.interests.map((tag, index) => (
                  <Chip key={`${index}-${tag}`}>{tag}</Chip>
                ))}
              </div>
            </>
          ) : null}

          {data.lifestyle_tags?.length ? (
            <>
              <div style={{ height: 20 }} />
              <div className="section-label">{t("people.sections.lifestyle")}</div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {data.lifestyle_tags.map((tag, index) => (
                  <Chip key={`${index}-${tag}`}>{tag}</Chip>
                ))}
              </div>
            </>
          ) : null}
        </Card>

        <Card className="surface surface--inset">
          <div className="section-label">{t("people.sections.whereNext")}</div>
          <div className="match-actions-row">
            <Link
              href={`/chat/${data.user_id}`}
              className="btn btn-primary"
              style={{ textAlign: "center" }}
              onClick={() =>
                setChatThreadHeaderSeed(data.user_id, {
                  displayName: data.display_name,
                  avatarUrl: resolvePhoto(data) || null,
                })
              }
            >
              {t("people.actions.backToChat")}
            </Link>
            <Link href="/matches" className="btn btn-secondary" style={{ textAlign: "center" }}>
              {t("people.actions.matchesList")}
            </Link>
          </div>
        </Card>

        {!isDemoProfile ? (
          <Card className="surface surface--inset">
            <div className="section-label">{t("people.safety.title")}</div>
            <div className="match-actions-row">
              <button
                type="button"
                className="btn btn-ghost profile-safety__block"
                onClick={() => void handleBlockUser()}
                disabled={actionBusy !== null}
              >
                {actionBusy === "block" ? t("common.blocking") : t("people.safety.block")}
              </button>
              <Button
                type="button"
                variant="ghost"
                onClick={() => void handleIgnoreUser()}
                disabled={actionBusy !== null || ignored}
              >
                {ignored ? t("people.safety.ignored") : actionBusy === "ignore" ? t("people.safety.ignoring") : t("people.safety.ignore")}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setReportOpen(true)} disabled={actionBusy !== null}>
                {t("people.safety.report")}
              </Button>
            </div>
          </Card>
        ) : null}
      </PageShell>

      <ReportReasonModal
        open={reportOpen}
        reason={reportReason}
        busy={actionBusy === "report"}
        onSelect={setReportReason}
        onClose={() => setReportOpen(false)}
        onSubmit={() => void handleSubmitReport()}
      />
      <Toast text={resolveI18nText(toast, t)} onClose={() => setToast(null)} />
    </>
  );
}
