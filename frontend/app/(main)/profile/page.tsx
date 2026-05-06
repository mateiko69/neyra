"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, formatApiError, getToken, invalidateApiGetCache } from "../../../lib/api";
import { resolvePhoto } from "../../../lib/resolvePhoto";
import { apiFailureToI18nText } from "../../../lib/i18n/translateApiUserMessage";
import { resolveI18nText, type I18nText, rawI18nText } from "../../../lib/i18n/message";
import { PremiumBadge } from "../../components/trust/PremiumBadge";
import { VerifiedBadge } from "../../components/trust/VerifiedBadge";
import { PageHeader } from "../../components/PageHeader";
import { PageShell } from "../../components/PageShell";
import { Button, Card, Chip, Input, Skeleton, Textarea, Toast } from "../../components/ui";
import { useT } from "../../components/i18n/I18nProvider";
import { PhotoUploader } from "../../components/PhotoUploader";
import { SafeImg } from "../../components/SafeImg";
import { VerificationFlowModal } from "../../components/verification/VerificationFlowModal";

type ProfileMe = {
  display_name?: string;
  city?: string;
  age?: number | null;
  date_of_birth?: string | null;
  gender?: string | null;
  height_cm?: number | null;
  job_title?: string | null;
  last_active_at?: string | null;
  interested_in?: string | null;
  relationship_goal?: string | null;
  vibe?: string | null;
  min_preferred_age?: number | null;
  max_preferred_age?: number | null;
  bio?: string | null;
  interests?: string | null;
  lifestyle_tags?: string | null;
  photo_urls?: string | null;
  /** Server: false when object storage is not configured (uploads return 503). */
  photo_upload_available?: boolean;
  is_demo_profile?: boolean | null;
  demo_only_mode?: boolean;
  verified?: boolean | null;
  is_verified?: boolean | null;
  verification_status?: string | null;
  verification_type?: string | null;
  verification_level?: string | null;
  verification_badge_visible?: boolean | null;
  is_premium?: boolean | null;
  premium_until?: string | null;
  native_language?: string | null;
  additional_languages?: string | null;
};

function parseCsv(s: string | null | undefined): string[] {
  return (s || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

function joinCsv(items: string[]): string {
  return items.map((x) => x.trim()).filter(Boolean).join(",");
}

function moveItem<T>(arr: T[], from: number, to: number): T[] {
  if (from === to) return arr;
  if (from < 0 || from >= arr.length) return arr;
  if (to < 0 || to >= arr.length) return arr;
  const next = [...arr];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

function pct(done: number, total: number): number {
  if (total <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((done / total) * 100)));
}

type StrengthItem = { key: string; ok: boolean };

const INTEREST_TAGS = [
  "cooking",
  "travel",
  "gym",
  "music",
  "movies",
  "art",
  "books",
  "hiking",
  "coffee",
  "gaming",
  "fashion",
  "business",
  "animals",
  "nature",
  "cars",
  "photography",
  "dancing",
  "yoga",
  "tech",
] as const;

function ageFromDobIso(dobIso: string): number | null {
  const s = String(dobIso || "").trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return null;
  const dob = new Date(`${s}T00:00:00Z`);
  if (!Number.isFinite(dob.getTime())) return null;
  const now = new Date();
  let age = now.getUTCFullYear() - dob.getUTCFullYear();
  const m = now.getUTCMonth() - dob.getUTCMonth();
  if (m < 0 || (m === 0 && now.getUTCDate() < dob.getUTCDate())) age -= 1;
  return age;
}

export default function ProfilePage() {
  const router = useRouter();
  const { t } = useT("ProfilePage");

  const [toast, setToast] = useState<I18nText>(null);
  const [profile, setProfile] = useState<ProfileMe | null>(null);
  const [loading, setLoading] = useState(true);
  const [skeletonVisible, setSkeletonVisible] = useState(true);
  const [saving, setSaving] = useState<null | "photos" | "basics" | "prefs" | "languages" | "tags" | "bio">(null);
  const [editing, setEditing] = useState<null | "photos" | "basics" | "prefs" | "languages" | "tags" | "bio">(null);
  const [bioAiLoading, setBioAiLoading] = useState(false);
  const [bioAiOptions, setBioAiOptions] = useState<string[]>([]);
  const [verifyOpen, setVerifyOpen] = useState(false);
  const [emailVerified, setEmailVerified] = useState(false);

  // Drafts
  const [draftPhotos, setDraftPhotos] = useState<{ urls: string[]; primaryIndex: number }>({ urls: [], primaryIndex: 0 });
  const [draftBasics, setDraftBasics] = useState<{
    display_name: string;
    city: string;
    gender: string;
    date_of_birth: string;
    height_cm: string;
    job_title: string;
  }>({
    display_name: "",
    city: "",
    gender: "",
    date_of_birth: "",
    height_cm: "",
    job_title: "",
  });
  const [draftPrefs, setDraftPrefs] = useState<{
    relationship_goal: string;
    interested_in: string;
    vibe: string;
    min_preferred_age: string;
    max_preferred_age: string;
  }>({
    relationship_goal: "",
    interested_in: "",
    vibe: "",
    min_preferred_age: "18",
    max_preferred_age: "35",
  });
  const [draftLanguages, setDraftLanguages] = useState<{ native_language: string; additional_languages: string[] }>({
    native_language: "",
    additional_languages: [],
  });
  const [draftTags, setDraftTags] = useState<{ interests: string[] }>({ interests: [] });
  const [draftBio, setDraftBio] = useState<{ bio: string; interests: string; lifestyle_tags: string }>({
    bio: "",
    interests: "",
    lifestyle_tags: "",
  });

  const loadGenRef = useRef(0);

  const hydrateDrafts = useCallback((p: ProfileMe) => {
    const urls = parseCsv(p.photo_urls);
    setDraftPhotos({ urls, primaryIndex: 0 });
    setDraftBasics({
      display_name: String(p.display_name || ""),
      city: String(p.city || ""),
      gender: String(p.gender || ""),
      date_of_birth: String(p.date_of_birth || ""),
      height_cm: p.height_cm != null ? String(p.height_cm) : "",
      job_title: String(p.job_title || ""),
    });
    setDraftPrefs({
      relationship_goal: String(p.relationship_goal || ""),
      interested_in: String(p.interested_in || ""),
      vibe: String(p.vibe || ""),
      min_preferred_age: p.min_preferred_age != null ? String(p.min_preferred_age) : "18",
      max_preferred_age: p.max_preferred_age != null ? String(p.max_preferred_age) : "35",
    });
    setDraftLanguages({
      native_language: String(p.native_language || ""),
      additional_languages: parseCsv(p.additional_languages),
    });
    setDraftTags({ interests: parseCsv(p.interests) });
    setDraftBio({
      bio: String(p.bio || ""),
      interests: String(p.interests || ""),
      lifestyle_tags: String(p.lifestyle_tags || ""),
    });
  }, []);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    let cancelled = false;
    loadGenRef.current += 1;
    const gen = loadGenRef.current;
    setLoading(true);
    setSkeletonVisible(true);
    const skeletonTimer = window.setTimeout(() => setSkeletonVisible(false), 500);
    void Promise.all([
      apiFetch("/profiles/me", { method: "GET", metaReason: "profile-load" }),
      apiFetch("/auth/me", { method: "GET", metaReason: "profile-load-auth", skipThrottle: true }).catch(() => null),
    ])
      .then(([p, me]) => {
        if (cancelled) return;
        if (gen !== loadGenRef.current) return;
        const next = p as ProfileMe;
        // eslint-disable-next-line no-console
        console.log("profile_loaded", next);
        setProfile(next);
        hydrateDrafts(next);
        if (me && typeof me === "object") setEmailVerified(Boolean((me as { email_verified?: boolean }).email_verified));
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (gen !== loadGenRef.current) return;
        setToast(apiFailureToI18nText(e, t, "profile.errors.load", formatApiError));
      })
      .finally(() => {
        window.clearTimeout(skeletonTimer);
        if (!cancelled && gen === loadGenRef.current) {
          setSkeletonVisible(false);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
      window.clearTimeout(skeletonTimer);
    };
  }, [hydrateDrafts, router, t]);

  const photoUploadDisabled = Boolean(profile?.photo_upload_available === false || profile?.demo_only_mode || profile?.is_demo_profile);

  useEffect(() => {
    if (photoUploadDisabled && editing === "photos") {
      setEditing(null);
    }
  }, [photoUploadDisabled, editing]);

  const strength = useMemo(() => {
    const p = profile;
    if (!p) return { percent: 0, missing: [] as string[], items: [] as StrengthItem[] };
    const photos = parseCsv(p.photo_urls);
    const interestCount = parseCsv(p.interests).length;
    const items: StrengthItem[] = [
      { key: "profile.strength.photos", ok: photos.length >= 1 },
      { key: "profile.strength.city", ok: Boolean(String(p.city || "").trim()) },
      { key: "profile.strength.tags", ok: interestCount >= 3 },
      { key: "profile.strength.bio", ok: String(p.bio || "").trim().length >= 30 },
    ];
    const done = items.filter((x) => x.ok).length;
    const missing = items.filter((x) => !x.ok).map((x) => x.key);
    return { percent: pct(done, items.length), missing, items };
  }, [profile]);

  const onSave = useCallback(
    async (section: "photos" | "basics" | "prefs" | "languages" | "tags" | "bio") => {
      if (!profile) return;
      if (section === "photos" && photoUploadDisabled) {
        setToast(rawI18nText(t("profile.photos.uploadUnavailableToast")));
        return;
      }
      if (saving) return;
      setSaving(section);
      try {
        let payload: Record<string, unknown> = {};
        if (section === "photos") {
          // Move chosen primary to front before saving.
          const urls = [...draftPhotos.urls];
          const pi = Math.max(0, Math.min(urls.length - 1, draftPhotos.primaryIndex));
          if (urls.length > 1 && pi > 0) {
            const [main] = urls.splice(pi, 1);
            urls.unshift(main);
          }
          payload = { photo_urls: joinCsv(urls) };
        } else if (section === "basics") {
          const height = Number(draftBasics.height_cm);
          const height_cm = Number.isFinite(height) ? Math.trunc(height) : null;
          payload = {
            display_name: draftBasics.display_name.trim(),
            city: draftBasics.city.trim(),
            gender: draftBasics.gender.trim(),
            date_of_birth: draftBasics.date_of_birth.trim() || null,
            height_cm,
            job_title: draftBasics.job_title.trim(),
          };
        } else if (section === "prefs") {
          const minRaw = Number(draftPrefs.min_preferred_age);
          const maxRaw = Number(draftPrefs.max_preferred_age);
          const min = Number.isFinite(minRaw) ? Math.max(18, Math.min(80, Math.trunc(minRaw))) : null;
          const max = Number.isFinite(maxRaw) ? Math.max(18, Math.min(80, Math.trunc(maxRaw))) : null;
          if (min == null || max == null) {
            setToast(rawI18nText(t("profile.errors.ageRange")));
            return;
          }
          if (max < min) {
            setToast(rawI18nText(t("profile.errors.ageRange")));
            return;
          }
          payload = {
            relationship_goal: draftPrefs.relationship_goal.trim(),
            interested_in: draftPrefs.interested_in.trim(),
            vibe: draftPrefs.vibe.trim(),
            min_preferred_age: min,
            max_preferred_age: max,
          };
        } else if (section === "languages") {
          payload = {
            native_language: draftLanguages.native_language.trim(),
            additional_languages: joinCsv(draftLanguages.additional_languages),
          };
        } else if (section === "tags") {
          payload = { interests: joinCsv(draftTags.interests) };
        } else {
          payload = {
            bio: draftBio.bio,
            lifestyle_tags: draftBio.lifestyle_tags,
          };
        }

        const next = (await apiFetch("/profiles/me", {
          method: "PATCH",
          metaReason: `profile-save:${section}`,
          body: JSON.stringify(payload),
          skipThrottle: true,
          skipCache: true,
        })) as ProfileMe;
        invalidateApiGetCache("/profiles/me");
        setProfile(next);
        hydrateDrafts(next);
        setEditing(null);
        setToast(rawI18nText(t("profile.saved")));
      } catch (e: unknown) {
        setToast(apiFailureToI18nText(e, t, "profile.errors.saveFailed", formatApiError));
      } finally {
        setSaving(null);
      }
    },
    [draftBasics, draftBio, draftLanguages, draftPhotos, draftPrefs, draftTags, hydrateDrafts, photoUploadDisabled, profile, saving, t],
  );

  const onCancel = useCallback(
    (section: "photos" | "basics" | "prefs" | "languages" | "tags" | "bio") => {
      if (!profile) return;
      hydrateDrafts(profile);
      if (editing === section) setEditing(null);
    },
    [editing, hydrateDrafts, profile],
  );

  const vStatus = String(profile?.verification_status || "").toLowerCase();
  const verified = Boolean(profile?.is_verified ?? profile?.verified) || vStatus === "approved" || vStatus === "verified";
  const verificationPending = vStatus === "pending" || vStatus === "pending_manual_review";
  const verificationManualReview = vStatus === "pending_manual_review";
  const verificationRejected = vStatus === "rejected";
  const showVerifiedBadge = verified && profile?.verification_badge_visible !== false;
  const isPremium = Boolean(profile?.is_premium);
  const primaryPhoto = profile ? resolvePhoto(profile) : "";
  const lastActiveLabel = useMemo(() => {
    const raw = String(profile?.last_active_at || "").trim();
    if (!raw) return null;
    const ms = Date.parse(raw);
    if (!Number.isFinite(ms)) return null;
    const ageMin = Math.max(0, Math.round((Date.now() - ms) / 60000));
    if (ageMin <= 5) return t("profile.lastActive.now");
    if (ageMin < 60) return t("profile.lastActive.minutes", { m: ageMin });
    const ageH = Math.round(ageMin / 60);
    if (ageH < 24) return t("profile.lastActive.hours", { h: ageH });
    const ageD = Math.round(ageH / 24);
    return t("profile.lastActive.days", { d: ageD });
  }, [profile?.last_active_at, t]);
  const derivedAge = useMemo(() => {
    const dob = String(profile?.date_of_birth || "").trim();
    if (dob) return ageFromDobIso(dob);
    const a = profile?.age;
    return a == null ? null : Math.trunc(Number(a));
  }, [profile?.age, profile?.date_of_birth]);
  const isEmptyProfile = useMemo(() => {
    if (!profile) return true;
    const nameOk = Boolean(String(profile.display_name || "").trim());
    const photosOk = parseCsv(profile.photo_urls).length >= 1;
    return !(nameOk || photosOk);
  }, [profile]);

  const onSuggestBio = useCallback(async () => {
    if (bioAiLoading) return;
    setBioAiLoading(true);
    setBioAiOptions([]);
    try {
      const interests = editing === "tags" ? draftTags.interests : parseCsv(profile?.interests);
      const city = String((editing === "basics" ? draftBasics.city : profile?.city) || "").trim();
      const res = (await apiFetch("/ai/bio-suggest", {
        method: "POST",
        metaReason: "profile-bio-suggest",
        body: JSON.stringify({ interests, city }),
        skipThrottle: true,
        skipCache: true,
      })) as { options?: string[] };
      const opts = Array.isArray(res?.options) ? res.options.map((x) => String(x || "").trim()).filter(Boolean) : [];
      if (opts.length) setBioAiOptions(opts.slice(0, 3));
      else setToast(rawI18nText(t("profile.bioHelper.empty")));
    } catch (e: unknown) {
      setToast(apiFailureToI18nText(e, t, "profile.bioHelper.error", formatApiError));
    } finally {
      setBioAiLoading(false);
    }
  }, [bioAiLoading, draftBasics.city, draftTags.interests, editing, profile?.city, profile?.interests, t]);

  const refreshProfile = useCallback(async () => {
    try {
      const next = (await apiFetch("/profiles/me", { method: "GET", metaReason: "profile-after-verify", skipThrottle: true, skipCache: true })) as ProfileMe;
      invalidateApiGetCache("/profiles/me");
      setProfile(next);
      hydrateDrafts(next);
    } catch {
      /* ignore */
    }
  }, [hydrateDrafts]);

  return (
    <PageShell>
      <VerificationFlowModal open={verifyOpen} onClose={() => setVerifyOpen(false)} onComplete={() => void refreshProfile()} />
      <PageHeader
        title={t("profile.header.title")}
        subtitle={t("profile.header.subtitle")}
        badge={
          showVerifiedBadge || isPremium || emailVerified ? (
            <span style={{ display: "inline-flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              {emailVerified ? (
                <Chip>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>{t("trust.emailConfirmed")}</span>
                </Chip>
              ) : null}
              {showVerifiedBadge ? (
                <Chip>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    <VerifiedBadge title={t("trust.verified.tooltip")} />
                    {t("profile.verified")}
                  </span>
                </Chip>
              ) : null}
              {isPremium ? (
                <Chip>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    <PremiumBadge title={t("premium.badge")} />
                    {t("premium.badge")}
                  </span>
                </Chip>
              ) : null}
            </span>
          ) : null
        }
      />

      <div className="grid" style={{ maxWidth: 920, margin: "0 auto", width: "100%" }}>
        {loading && skeletonVisible ? (
          <>
            <Card className="surface" style={{ padding: 16 }}>
              <Skeleton style={{ height: 20, width: 220, borderRadius: 10 }} />
              <div style={{ height: 10 }} />
              <Skeleton style={{ height: 10, width: "100%", borderRadius: 999 }} />
              <div style={{ height: 12 }} />
              <Skeleton style={{ height: 14, width: 320, borderRadius: 10 }} />
            </Card>
            {[0, 1, 2, 3].map((k) => (
              <Card key={k} className="surface" style={{ padding: 16 }}>
                <Skeleton style={{ height: 16, width: 180, borderRadius: 10 }} />
                <div style={{ height: 12 }} />
                <Skeleton style={{ height: 44, width: "100%", borderRadius: 14 }} />
                <div style={{ height: 10 }} />
                <Skeleton style={{ height: 44, width: "100%", borderRadius: 14 }} />
              </Card>
            ))}
          </>
        ) : null}

        {loading && !skeletonVisible ? (
          <Card className="surface" style={{ padding: 16 }}>
            <div className="caption" style={{ opacity: 0.85 }}>
              {t("common.loading")}
            </div>
          </Card>
        ) : null}

        {!loading && isEmptyProfile ? (
          <Card className="surface" style={{ padding: 16 }}>
            <div className="h2" style={{ fontSize: 20, fontWeight: 900 }}>
              {t("profile.empty.title")}
            </div>
            <div className="caption" style={{ marginTop: 8, opacity: 0.85, lineHeight: 1.35 }}>
              {t("profile.empty.description")}
            </div>
            <div style={{ marginTop: 14, display: "flex", gap: 10, flexWrap: "wrap" }}>
              <Button type="button" onClick={() => router.push("/onboarding")}>
                {t("profile.empty.ctaComplete")}
              </Button>
              <Button type="button" variant="secondary" onClick={() => router.push("/discover")}>
                {t("navigation.discover")}
              </Button>
            </div>
          </Card>
        ) : null}

        {!loading && profile && !isEmptyProfile ? (
        <Card className="surface" style={{ padding: 16 }}>
          <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
            <div style={{ width: 56, height: 56, borderRadius: 16, overflow: "hidden", background: "rgba(255,255,255,0.06)" }}>
              <SafeImg
                src={primaryPhoto || null}
                alt=""
                style={{ width: "100%", height: "100%", objectFit: "cover" }}
                loading="eager"
              />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="h2" style={{ fontSize: 22 }}>
                {t("profile.strength.title")} — {strength.percent}%
              </div>
              <div style={{ marginTop: 8, height: 10, borderRadius: 999, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                <div style={{ width: `${strength.percent}%`, height: "100%", background: "rgba(120,255,200,0.9)" }} />
              </div>
              {strength.missing.length ? (
                <div className="caption" style={{ marginTop: 10, opacity: 0.85, lineHeight: 1.35 }}>
                  {t("profile.strength.missing")}{" "}
                  {strength.missing.map((k) => (
                    <span key={k} style={{ marginRight: 8 }}>
                      • {t(k)}
                    </span>
                  ))}
                </div>
              ) : (
                <div className="caption" style={{ marginTop: 10, opacity: 0.85 }}>
                  {t("profile.strength.perfect")}
                </div>
              )}
              {lastActiveLabel ? (
                <div className="caption" style={{ marginTop: 8, opacity: 0.82 }}>
                  {t("profile.lastActive.label")}: {lastActiveLabel}
                </div>
              ) : null}
              {(() => {
                const count = parseCsv(profile?.interests).length;
                const need = Math.max(0, 3 - count);
                if (need <= 0) return null;
                // Product copy requested: “Add 2 interests — +30% matches” (keep it simple).
                const n = Math.min(2, need);
                return (
                  <div className="caption" style={{ marginTop: 8, opacity: 0.9 }}>
                    {t("profile.suggestion.addInterests", { n, boost: 30 })}
                  </div>
                );
              })()}
            </div>
            <Button type="button" variant="secondary" onClick={() => router.push("/discover")}>
              {t("navigation.discover")}
            </Button>
          </div>
        </Card>
        ) : null}

        {!loading && profile && !isEmptyProfile ? (
          <Card id="trust-status" className={`surface profile-verification-card ${isPremium ? "profile-trust-card--premium" : ""}`.trim()} style={{ padding: 18 }}>
            <div className="section-label">{t("profile.trustStatus.title")}</div>
            <div style={{ marginTop: 14, display: "grid", gap: 12 }}>
              <div className="body" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <strong>{t("premium.badge")}:</strong>
                <span>{isPremium ? t("profile.trustStatus.premiumYes") : t("profile.trustStatus.premiumNo")}</span>
              </div>

              {showVerifiedBadge ? (
                <div className="profile-verification-card__verified">
                  <div className="profile-verification-card__badge-row">
                    <span className="profile-verification-card__check" aria-hidden>
                      ✓
                    </span>
                    <span className="h2" style={{ fontSize: 18, fontWeight: 800, margin: 0 }}>
                      {t("profile.verification.card.verifiedTitle")}
                    </span>
                  </div>
                  <p className="caption" style={{ margin: 0, opacity: 0.88, lineHeight: 1.45 }}>
                    {t("profile.verification.card.verifiedSub")}
                  </p>
                  <p className="caption" style={{ margin: 0, opacity: 0.75, lineHeight: 1.45, fontSize: 13 }}>
                    {t("profile.verification.card.boostLine")}
                  </p>
                </div>
              ) : verificationPending ? (
                <div className="profile-verification-card__pending">
                  <div className="h2" style={{ fontSize: 18, fontWeight: 800, margin: 0 }}>
                    {verificationManualReview ? t("profile.verification.card.pendingManualTitle") : t("profile.verification.card.pendingTitle")}
                  </div>
                  <p className="caption" style={{ margin: 0, opacity: 0.88, lineHeight: 1.45 }}>
                    {verificationManualReview ? t("profile.verification.card.pendingManualSub") : t("profile.verification.card.pendingSub")}
                  </p>
                  <Button type="button" variant="secondary" className="profile-verification-card__btn" onClick={() => setVerifyOpen(true)}>
                    {t("profile.verification.card.ctaRetry")}
                  </Button>
                </div>
              ) : (
                <div className="profile-verification-card__cta-block">
                  <div className="h2" style={{ fontSize: 20, fontWeight: 900, margin: 0 }}>
                    {t("profile.verification.card.title")}
                  </div>
                  <p className="body" style={{ margin: 0, opacity: 0.9, lineHeight: 1.45 }}>
                    {t("profile.verification.card.subtitle")}
                  </p>
                  <p className="caption" style={{ margin: 0, opacity: 0.78, lineHeight: 1.45 }}>
                    {t("profile.verification.card.boostLine")}
                  </p>
                  <Button type="button" variant="primary" className="profile-verification-card__btn" onClick={() => setVerifyOpen(true)}>
                    {verificationRejected ? t("profile.verification.card.ctaRetry") : t("profile.verification.card.cta")}
                  </Button>
                </div>
              )}
            </div>
          </Card>
        ) : null}

        {/* Photos */}
        {!loading ? (
        <Card className="surface" style={{ padding: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
            <div>
              <div className="section-label">{t("profile.section.photos")}</div>
              <div className="caption" style={{ opacity: 0.85, marginTop: 6 }}>
                {t("profile.section.photos.subtitle")}
              </div>
              {photoUploadDisabled ? (
                <div
                  className="caption"
                  role="status"
                  style={{
                    marginTop: 10,
                    padding: "10px 12px",
                    borderRadius: 12,
                    border: "1px solid rgba(255, 255, 255, 0.14)",
                    background: "rgba(255, 255, 255, 0.05)",
                    lineHeight: 1.45,
                    opacity: 0.92,
                  }}
                >
                  {profile?.is_demo_profile || profile?.demo_only_mode
                    ? t("profile.photos.uploadDisabledDemo")
                    : t("profile.photos.uploadDisabledGeneric")}
                </div>
              ) : null}
            </div>
            {editing === "photos" ? (
              <div style={{ display: "flex", gap: 10 }}>
                <Button variant="ghost" onClick={() => onCancel("photos")} disabled={saving === "photos"}>
                  {t("common.cancel")}
                </Button>
                <Button
                  onClick={() => void onSave("photos")}
                  disabled={saving === "photos" || photoUploadDisabled}
                >
                  {saving === "photos" ? t("common.saving") : t("common.save")}
                </Button>
              </div>
            ) : (
              <Button
                type="button"
                data-testid="profile-photo-edit"
                variant="secondary"
                onClick={() => setEditing("photos")}
                disabled={photoUploadDisabled}
              >
                {t("common.edit")}
              </Button>
            )}
          </div>

          <div style={{ marginTop: 12 }}>
            <PhotoUploader
              urls={editing === "photos" ? draftPhotos.urls : parseCsv(profile?.photo_urls)}
              primaryIndex={editing === "photos" ? draftPhotos.primaryIndex : 0}
              disabled={photoUploadDisabled || editing !== "photos" || saving === "photos"}
              onChange={(urls, primaryIndex) => setDraftPhotos({ urls, primaryIndex })}
              onError={(msg) => setToast(msg)}
            />
          </div>
        </Card>
        ) : null}

        {/* Basic info */}
        {!loading ? (
        <Card className="surface" style={{ padding: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
            <div>
              <div className="section-label">{t("profile.section.basics")}</div>
              <div className="caption" style={{ opacity: 0.85, marginTop: 6 }}>
                {t("profile.section.basics.subtitle")}
              </div>
            </div>
            {editing === "basics" ? (
              <div style={{ display: "flex", gap: 10 }}>
                <Button variant="ghost" onClick={() => onCancel("basics")} disabled={saving === "basics"}>
                  {t("common.cancel")}
                </Button>
                <Button onClick={() => void onSave("basics")} disabled={saving === "basics"}>
                  {saving === "basics" ? t("common.saving") : t("common.save")}
                </Button>
              </div>
            ) : (
              <Button variant="secondary" onClick={() => setEditing("basics")}>
                {t("common.edit")}
              </Button>
            )}
          </div>

          <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
            <div>
              <div className="caption">{t("profile.field.name")}</div>
              <Input
                value={editing === "basics" ? draftBasics.display_name : String(profile?.display_name || "")}
                disabled={editing !== "basics"}
                onChange={(e) => setDraftBasics((d) => ({ ...d, display_name: e.target.value }))}
              />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div>
                <div className="caption">{t("profile.field.city")}</div>
                <Input
                  value={editing === "basics" ? draftBasics.city : String(profile?.city || "")}
                  disabled={editing !== "basics"}
                  onChange={(e) => setDraftBasics((d) => ({ ...d, city: e.target.value }))}
                />
              </div>
              <div>
                <div className="caption">{t("profile.field.gender")}</div>
                <select
                  className="input"
                  value={editing === "basics" ? draftBasics.gender : String(profile?.gender || "")}
                  disabled={editing !== "basics"}
                  onChange={(e) => setDraftBasics((d) => ({ ...d, gender: e.target.value }))}
                >
                  <option value="">{t("common.none")}</option>
                  <option value="man">{t("profile.gender.man")}</option>
                  <option value="woman">{t("profile.gender.woman")}</option>
                  <option value="nonbinary">{t("profile.gender.nonbinary")}</option>
                </select>
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div>
                <div className="caption">{t("profile.field.dob")}</div>
                <Input
                  type="date"
                  value={editing === "basics" ? draftBasics.date_of_birth : String(profile?.date_of_birth || "")}
                  disabled={editing !== "basics"}
                  onChange={(e) => setDraftBasics((d) => ({ ...d, date_of_birth: e.target.value }))}
                />
              </div>
              <div>
                <div className="caption">{t("profile.field.age")}</div>
                <Input value={derivedAge == null ? "" : String(derivedAge)} disabled />
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div>
                <div className="caption">{t("profile.field.height")}</div>
                <Input
                  inputMode="numeric"
                  value={editing === "basics" ? draftBasics.height_cm : String(profile?.height_cm ?? "")}
                  disabled={editing !== "basics"}
                  onChange={(e) => setDraftBasics((d) => ({ ...d, height_cm: e.target.value }))}
                  placeholder={t("profile.field.height.placeholder")}
                />
              </div>
              <div>
                <div className="caption">{t("profile.field.job")}</div>
                <Input
                  value={editing === "basics" ? draftBasics.job_title : String(profile?.job_title || "")}
                  disabled={editing !== "basics"}
                  onChange={(e) => setDraftBasics((d) => ({ ...d, job_title: e.target.value }))}
                  placeholder={t("profile.field.job.placeholder")}
                />
              </div>
            </div>
          </div>
        </Card>
        ) : null}

        {/* Languages */}
        {!loading ? (
        <Card className="surface" style={{ padding: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
            <div>
              <div className="section-label">{t("profile.section.languages")}</div>
              <div className="caption" style={{ opacity: 0.85, marginTop: 6 }}>
                {t("profile.section.languages.subtitle")}
              </div>
            </div>
            {editing === "languages" ? (
              <div style={{ display: "flex", gap: 10 }}>
                <Button variant="ghost" onClick={() => onCancel("languages")} disabled={saving === "languages"}>
                  {t("common.cancel")}
                </Button>
                <Button onClick={() => void onSave("languages")} disabled={saving === "languages"}>
                  {saving === "languages" ? t("common.saving") : t("common.save")}
                </Button>
              </div>
            ) : (
              <Button variant="secondary" onClick={() => setEditing("languages")}>
                {t("common.edit")}
              </Button>
            )}
          </div>

          <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
            <div>
              <div className="caption">{t("profile.field.nativeLanguage")}</div>
              <Input
                value={editing === "languages" ? draftLanguages.native_language : String(profile?.native_language || "")}
                disabled={editing !== "languages"}
                onChange={(e) => setDraftLanguages((d) => ({ ...d, native_language: e.target.value }))}
                placeholder={t("profile.field.nativeLanguage.placeholder")}
              />
            </div>
            <div>
              <div className="caption">{t("profile.field.additionalLanguages")}</div>
              <Input
                value={
                  editing === "languages"
                    ? draftLanguages.additional_languages.join(", ")
                    : parseCsv(profile?.additional_languages).join(", ")
                }
                disabled={editing !== "languages"}
                onChange={(e) =>
                  setDraftLanguages((d) => ({
                    ...d,
                    additional_languages: parseCsv(e.target.value),
                  }))
                }
                placeholder={t("profile.field.additionalLanguages.placeholder")}
              />
              <div className="caption" style={{ marginTop: 6, opacity: 0.75 }}>
                {t("profile.field.additionalLanguages.hint")}
              </div>
            </div>
          </div>
        </Card>
        ) : null}

        {/* Tags / Interests */}
        {!loading ? (
        <Card className="surface" style={{ padding: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
            <div>
              <div className="section-label">{t("profile.section.tags")}</div>
              <div className="caption" style={{ opacity: 0.85, marginTop: 6 }}>
                {t("profile.section.tags.subtitle", { max: 10 })}
              </div>
            </div>
            {editing === "tags" ? (
              <div style={{ display: "flex", gap: 10 }}>
                <Button variant="ghost" onClick={() => onCancel("tags")} disabled={saving === "tags"}>
                  {t("common.cancel")}
                </Button>
                <Button onClick={() => void onSave("tags")} disabled={saving === "tags"}>
                  {saving === "tags" ? t("common.saving") : t("common.save")}
                </Button>
              </div>
            ) : (
              <Button variant="secondary" onClick={() => setEditing("tags")}>
                {t("common.edit")}
              </Button>
            )}
          </div>

          {editing === "tags" ? (
            <div style={{ marginTop: 12 }}>
              <div className="caption" style={{ opacity: 0.85, marginBottom: 8 }}>
                {t("profile.section.tags.priority")}
              </div>
              {draftTags.interests.length ? (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                  {draftTags.interests.map((tag, idx) => (
                    <div key={`${tag}-${idx}`} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <div
                        className="chip"
                        style={{
                          padding: "8px 12px",
                          borderRadius: 999,
                          border: "1px solid rgba(255,255,255,0.14)",
                          background: "rgba(180,120,255,0.22)",
                          color: "rgba(255,255,255,0.95)",
                        }}
                      >
                        {t(`profile.interests.${tag}`)}
                      </div>
                      <button
                        type="button"
                        className="chip"
                        disabled={saving === "tags" || idx === 0}
                        style={{
                          padding: "8px 10px",
                          borderRadius: 999,
                          border: "1px solid rgba(255,255,255,0.14)",
                          background: "rgba(255,255,255,0.06)",
                          color: "rgba(255,255,255,0.95)",
                          cursor: saving === "tags" || idx === 0 ? "default" : "pointer",
                          opacity: saving === "tags" || idx === 0 ? 0.55 : 1,
                        }}
                        onClick={() => setDraftTags((d) => ({ interests: moveItem(d.interests, idx, idx - 1) }))}
                        aria-label={t("profile.section.tags.moveUp")}
                        title={t("profile.section.tags.moveUp")}
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        className="chip"
                        disabled={saving === "tags" || idx === draftTags.interests.length - 1}
                        style={{
                          padding: "8px 10px",
                          borderRadius: 999,
                          border: "1px solid rgba(255,255,255,0.14)",
                          background: "rgba(255,255,255,0.06)",
                          color: "rgba(255,255,255,0.95)",
                          cursor: saving === "tags" || idx === draftTags.interests.length - 1 ? "default" : "pointer",
                          opacity: saving === "tags" || idx === draftTags.interests.length - 1 ? 0.55 : 1,
                        }}
                        onClick={() => setDraftTags((d) => ({ interests: moveItem(d.interests, idx, idx + 1) }))}
                        aria-label={t("profile.section.tags.moveDown")}
                        title={t("profile.section.tags.moveDown")}
                      >
                        ↓
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="caption" style={{ opacity: 0.75 }}>
                  {t("profile.section.tags.priority.empty")}
                </div>
              )}
            </div>
          ) : null}

          <div style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 10 }}>
            {(INTEREST_TAGS as readonly string[]).map((tag) => {
              const selected = (editing === "tags" ? draftTags.interests : parseCsv(profile?.interests)).includes(tag);
              const disabled = editing !== "tags" || saving === "tags";
              return (
                <button
                  key={tag}
                  type="button"
                  disabled={disabled}
                  className="chip"
                  style={{
                    padding: "8px 12px",
                    borderRadius: 999,
                    border: "1px solid rgba(255,255,255,0.14)",
                    background: selected ? "rgba(180,120,255,0.22)" : "rgba(255,255,255,0.06)",
                    color: "rgba(255,255,255,0.95)",
                    cursor: disabled ? "default" : "pointer",
                  }}
                  onClick={() => {
                    if (disabled) return;
                    setDraftTags((d) => {
                      const cur = d.interests || [];
                      const has = cur.includes(tag);
                      if (has) return { interests: cur.filter((x) => x !== tag) };
                      if (cur.length >= 10) return d;
                      return { interests: [...cur, tag] };
                    });
                  }}
                >
                  {t(`profile.interests.${tag}`)}
                  {selected ? " ✓" : ""}
                </button>
              );
            })}
          </div>
          <div className="caption" style={{ marginTop: 10, opacity: 0.8 }}>
            {t("profile.section.tags.count", { count: (editing === "tags" ? draftTags.interests : parseCsv(profile?.interests)).length, max: 10 })}
          </div>
        </Card>
        ) : null}

        {/* Preferences */}
        {!loading ? (
        <Card className="surface" style={{ padding: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
            <div>
              <div className="section-label">{t("profile.section.prefs")}</div>
              <div className="caption" style={{ opacity: 0.85, marginTop: 6 }}>
                {t("profile.section.prefs.subtitle")}
              </div>
            </div>
            {editing === "prefs" ? (
              <div style={{ display: "flex", gap: 10 }}>
                <Button variant="ghost" onClick={() => onCancel("prefs")} disabled={saving === "prefs"}>
                  {t("common.cancel")}
                </Button>
                <Button onClick={() => void onSave("prefs")} disabled={saving === "prefs"}>
                  {saving === "prefs" ? t("common.saving") : t("common.save")}
                </Button>
              </div>
            ) : (
              <Button variant="secondary" onClick={() => setEditing("prefs")}>
                {t("common.edit")}
              </Button>
            )}
          </div>

          <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div>
                <div className="caption">{t("profile.field.lookingFor")}</div>
                <select
                  className="input"
                  value={editing === "prefs" ? draftPrefs.relationship_goal : String(profile?.relationship_goal || "")}
                  disabled={editing !== "prefs"}
                  onChange={(e) => setDraftPrefs((d) => ({ ...d, relationship_goal: e.target.value }))}
                >
                  <option value="">{t("common.none")}</option>
                  <option value="dating">{t("onboarding.preferences.lookingFor.dating")}</option>
                  <option value="relationship">{t("onboarding.preferences.lookingFor.relationship")}</option>
                  <option value="chat">{t("onboarding.preferences.lookingFor.chat")}</option>
                </select>
              </div>
              <div>
                <div className="caption">{t("profile.field.interestedIn")}</div>
                <select
                  className="input"
                  value={editing === "prefs" ? draftPrefs.interested_in : String(profile?.interested_in || "")}
                  disabled={editing !== "prefs"}
                  onChange={(e) => setDraftPrefs((d) => ({ ...d, interested_in: e.target.value }))}
                >
                  <option value="">{t("common.none")}</option>
                  <option value="women">{t("onboarding.preferences.interestedIn.women")}</option>
                  <option value="men">{t("onboarding.preferences.interestedIn.men")}</option>
                  <option value="everyone">{t("onboarding.preferences.interestedIn.everyone")}</option>
                </select>
              </div>
            </div>

            <div>
              <div className="caption">{t("profile.field.vibe")}</div>
              <select
                className="input"
                value={editing === "prefs" ? draftPrefs.vibe : String(profile?.vibe || "")}
                disabled={editing !== "prefs"}
                onChange={(e) => setDraftPrefs((d) => ({ ...d, vibe: e.target.value }))}
              >
                <option value="">{t("common.none")}</option>
                <option value="warm">{t("onboarding.intent.vibe.warm")}</option>
                <option value="playful">{t("onboarding.intent.vibe.playful")}</option>
                <option value="grounded">{t("onboarding.intent.vibe.grounded")}</option>
                <option value="creative">{t("onboarding.intent.vibe.creative")}</option>
                <option value="adventurous">{t("onboarding.intent.vibe.adventurous")}</option>
              </select>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div>
                <div className="caption">{t("profile.field.ageMin")}</div>
                {editing === "prefs" ? (
                  <select
                    className="input"
                    value={draftPrefs.min_preferred_age}
                    disabled={saving === "prefs"}
                    onChange={(e) => {
                      const v = Math.max(18, Math.min(80, Math.trunc(Number(e.target.value || 18))));
                      setDraftPrefs((d) => {
                        const curMax = Math.max(18, Math.min(80, Math.trunc(Number(d.max_preferred_age || 35))));
                        return { ...d, min_preferred_age: String(v), max_preferred_age: String(Math.max(v, curMax)) };
                      });
                    }}
                  >
                    {Array.from({ length: 63 }, (_, i) => 18 + i).map((n) => (
                      <option key={n} value={String(n)}>
                        {n}
                      </option>
                    ))}
                  </select>
                ) : (
                  <Input value={String(profile?.min_preferred_age ?? "")} disabled />
                )}
              </div>
              <div>
                <div className="caption">{t("profile.field.ageMax")}</div>
                {editing === "prefs" ? (
                  <select
                    className="input"
                    value={draftPrefs.max_preferred_age}
                    disabled={saving === "prefs"}
                    onChange={(e) => {
                      const v = Math.max(18, Math.min(80, Math.trunc(Number(e.target.value || 35))));
                      setDraftPrefs((d) => ({ ...d, max_preferred_age: String(Math.max(Math.trunc(Number(d.min_preferred_age || 18)), v)) }));
                    }}
                  >
                    {Array.from({ length: 63 }, (_, i) => 18 + i).map((n) => (
                      <option key={n} value={String(n)}>
                        {n}
                      </option>
                    ))}
                  </select>
                ) : (
                  <Input value={String(profile?.max_preferred_age ?? "")} disabled />
                )}
              </div>
            </div>
            <div className="caption" style={{ opacity: 0.85 }}>
              {t("profile.partnerAgeRange.summary", {
                min: String(profile?.min_preferred_age ?? draftPrefs.min_preferred_age ?? "18"),
                max: String(profile?.max_preferred_age ?? draftPrefs.max_preferred_age ?? "35"),
              })}
            </div>
          </div>
        </Card>
        ) : null}

        {/* Bio */}
        {!loading ? (
        <Card className="surface" style={{ padding: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
            <div>
              <div className="section-label">{t("profile.section.bio")}</div>
              <div className="caption" style={{ opacity: 0.85, marginTop: 6 }}>
                {t("profile.section.bio.subtitle")}
              </div>
            </div>
            {editing === "bio" ? (
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
                <Button variant="secondary" onClick={() => void onSuggestBio()} disabled={saving === "bio" || bioAiLoading}>
                  {bioAiLoading ? t("profile.bioHelper.loading") : t("profile.bioHelper.suggest")}
                </Button>
                <Button variant="ghost" onClick={() => onCancel("bio")} disabled={saving === "bio"}>
                  {t("common.cancel")}
                </Button>
                <Button onClick={() => void onSave("bio")} disabled={saving === "bio"}>
                  {saving === "bio" ? t("common.saving") : t("common.save")}
                </Button>
              </div>
            ) : (
              <Button variant="secondary" onClick={() => setEditing("bio")}>
                {t("common.edit")}
              </Button>
            )}
          </div>

          <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
            {editing === "bio" && bioAiOptions.length ? (
              <div style={{ display: "grid", gap: 10 }}>
                <div className="caption" style={{ opacity: 0.85 }}>
                  {t("profile.bioHelper.pickOne")}
                </div>
                <div style={{ display: "grid", gap: 10 }}>
                  {bioAiOptions.map((opt, i) => (
                    <button
                      key={i}
                      type="button"
                      disabled={saving === "bio"}
                      className="surface"
                      style={{
                        textAlign: "left",
                        padding: 12,
                        borderRadius: 14,
                        border: "1px solid rgba(255,255,255,0.12)",
                        background: "rgba(255,255,255,0.04)",
                        color: "rgba(255,255,255,0.95)",
                        cursor: saving === "bio" ? "default" : "pointer",
                      }}
                      onClick={() => setDraftBio((d) => ({ ...d, bio: opt }))}
                    >
                      {opt}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            <div>
              <div className="caption">{t("profile.field.bio")}</div>
              <Textarea
                rows={6}
                value={editing === "bio" ? draftBio.bio : String(profile?.bio || "")}
                disabled={editing !== "bio"}
                onChange={(e) => setDraftBio((d) => ({ ...d, bio: e.target.value }))}
              />
              <div className="caption" style={{ marginTop: 6, opacity: 0.75 }}>
                {t("profile.field.bio.hint")}
              </div>
            </div>
            <div>
              <div className="caption">{t("profile.field.lifestyle")}</div>
              <Input
                value={editing === "bio" ? draftBio.lifestyle_tags : String(profile?.lifestyle_tags || "")}
                disabled={editing !== "bio"}
                onChange={(e) => setDraftBio((d) => ({ ...d, lifestyle_tags: e.target.value }))}
              />
            </div>
          </div>
        </Card>
        ) : null}
      </div>

      <Toast text={resolveI18nText(toast, t)} onClose={() => setToast(null)} />
    </PageShell>
  );
}

