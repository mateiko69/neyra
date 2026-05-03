"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ApiUnauthorizedError,
  apiFetch,
  applyAuthBootstrapResult,
  ensureAuthBootstrapped,
  invalidateApiGetCache,
} from "../../../lib/api";
import { invalidateAuthBootstrapCache, primeAuthBootstrapFromMe } from "../../../lib/auth/bootstrap";
import { PageShell } from "../../components/PageShell";
import { Button, Card, Input } from "../../components/ui";
import { useT } from "../../components/i18n/I18nProvider";
import { fetchGeoOnce } from "../../../lib/i18n/geo";
import { LOCALES, sortLocalesForSelect, type AppLocale } from "../../../lib/i18n/locales";
import { OnboardingDobFields } from "../../components/onboarding/OnboardingDobFields";
import { PhotoUploader } from "../../components/PhotoUploader";
import { photoUrlsForApi } from "../../../lib/photos";
import { ageFromIsoUtc } from "../../../lib/onboarding/dobIso";
import { resolveI18nText, type I18nText } from "../../../lib/i18n/message";
import { SafeImg } from "../../components/SafeImg";
import { FirstImpressionIntro } from "../../components/FirstImpressionIntro";
import {
  emptyOnboardingForm,
  profileToOnboardingFormPartial,
  type OnboardingFormShape,
} from "../../../lib/onboarding/profilePrefill";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { markOnboardingCompletedTimestamp } from "../../../lib/reviewPrompt";

const ONBOARDING_DRAFT_KEY = "neyra:onboarding:draft" as const;

const steps = ["name", "gender", "dob", "city", "photos", "languages", "intent", "tags", "done"] as const;
type StepId = (typeof steps)[number];

const MIN_INTEREST_TAGS = 2;

type OnboardingForm = OnboardingFormShape;

type OnboardingDraftV1 = { step?: number; form?: Partial<OnboardingForm> };

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

function clampStep(s: number): number {
  if (!Number.isFinite(s)) return 0;
  return Math.max(0, Math.min(steps.length - 1, Math.trunc(s)));
}

function readDraft(): OnboardingDraftV1 | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(ONBOARDING_DRAFT_KEY);
    if (!raw) return null;
    const o = JSON.parse(raw) as OnboardingDraftV1;
    return o && typeof o === "object" ? o : null;
  } catch {
    return null;
  }
}

function mergeForm(base: OnboardingForm, profilePart: Partial<OnboardingForm>, draftPart: Partial<OnboardingForm>): OnboardingForm {
  const photos = Array.isArray(draftPart.photos) ? draftPart.photos : profilePart.photos ?? base.photos;
  const primaryIndexRaw = draftPart.primaryIndex ?? profilePart.primaryIndex ?? base.primaryIndex;
  const primaryIndex = Math.max(0, Math.min(Math.max(0, photos.length - 1), Math.trunc(Number(primaryIndexRaw ?? 0))));
  return {
    ...base,
    ...profilePart,
    ...draftPart,
    photos,
    primaryIndex,
    tags: Array.isArray(draftPart.tags) ? draftPart.tags : profilePart.tags ?? base.tags,
    additional_languages: Array.isArray(draftPart.additional_languages)
      ? draftPart.additional_languages
      : profilePart.additional_languages ?? base.additional_languages,
  };
}

export default function OnboardingPage() {
  const router = useRouter();
  const { t, locale } = useT("OnboardingSimple");
  const [booting, setBooting] = useState(true);
  const [step, setStep] = useState(0);
  const stepId = steps[Math.max(0, Math.min(steps.length - 1, step))] as StepId;

  const [form, setForm] = useState<OnboardingForm>(() => emptyOnboardingForm(locale as AppLocale));

  const [error, setError] = useState<string>("");
  const [saving, setSaving] = useState(false);

  const derivedAge = useMemo(() => {
    const a = ageFromIsoUtc(form.date_of_birth);
    return a == null ? null : Math.trunc(a);
  }, [form.date_of_birth]);

  const topTags = useMemo(() => (form.tags || []).map((x) => String(x || "").trim()).filter(Boolean).slice(0, 3), [form.tags]);
  const previewPhoto = useMemo(() => String((form.photos || [])[0] || "").trim(), [form.photos]);
  const extraLangOptions = useMemo(
    () => sortLocalesForSelect(locale as AppLocale, LOCALES.map((l) => l.code)).filter((c) => c !== locale),
    [locale],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        await ensureAuthBootstrapped();
        const me = await apiFetch("/auth/me", {
          method: "GET",
          metaReason: "onboarding-mount",
          skipThrottle: true,
          skipCache: true,
        });
        if (cancelled) return;
        primeAuthBootstrapFromMe(me);
        applyAuthBootstrapResult({ status: "ok", me });

        const onboardingRequired = Boolean((me as { onboarding_required?: boolean })?.onboarding_required);
        if (!onboardingRequired) {
          router.replace("/discover");
          return;
        }

        let profile: unknown = null;
        try {
          profile = await apiFetch("/profiles/me", {
            method: "GET",
            metaReason: "onboarding-prefill",
            skipThrottle: true,
            skipCache: true,
          });
        } catch {
          profile = null;
        }
        if (cancelled) return;

        if (
          profile &&
          typeof profile === "object" &&
          Boolean((profile as { onboarding_completed?: boolean }).onboarding_completed)
        ) {
          router.replace("/discover");
          return;
        }

        const base = emptyOnboardingForm(locale as AppLocale);
        const fromProfile = profileToOnboardingFormPartial(profile);
        const draft = readDraft();
        const draftForm = (draft?.form || {}) as Partial<OnboardingForm>;
        const merged = mergeForm(base, fromProfile, draftForm);
        setForm(merged);
        if (draft?.step != null) setStep(clampStep(Number(draft.step)));
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiUnauthorizedError) {
          router.replace("/login");
          return;
        }
        setError(t("onboarding.errors.load"));
      } finally {
        if (!cancelled) setBooting(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // Intentionally once on mount: re-running would reset form/step mid-flow.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  useEffect(() => {
    if (booting) return;
    try {
      sessionStorage.setItem(ONBOARDING_DRAFT_KEY, JSON.stringify({ step, form }));
    } catch {
      /* ignore */
    }
  }, [step, form, booting]);

  useEffect(() => {
    // eslint-disable-next-line no-console
    console.log("[onboarding]", { step, form, errors: error ? [error] : [] });
  }, [step, error, form]);

  const hasFetchedGeoRef = useRef(false);
  useEffect(() => {
    if (booting) return;
    if (hasFetchedGeoRef.current) return;
    hasFetchedGeoRef.current = true;
    void fetchGeoOnce().then((obj) => {
      const city = String(obj?.city || "").trim();
      if (city) setForm((p) => ({ ...p, city: p.city.trim() ? p.city : city }));
    });
    return () => {
      hasFetchedGeoRef.current = false;
    };
  }, [booting]);

  const canNext = useMemo(() => {
    if (stepId === "name") return Boolean(form.name.trim());
    if (stepId === "gender") return Boolean(form.gender);
    if (stepId === "dob") {
      if (!form.date_of_birth.trim()) return false;
      const age = ageFromIsoUtc(form.date_of_birth);
      if (age == null) return false;
      return age >= 18;
    }
    if (stepId === "city") return Boolean(form.city.trim());
    if (stepId === "photos") return form.photos.length > 0;
    if (stepId === "languages") return Boolean(String(form.native_language || "").trim());
    if (stepId === "intent")
      return (
        Boolean(form.looking_for) &&
        Boolean(form.vibe) &&
        Boolean(form.interested_in) &&
        form.max_age >= form.min_age &&
        form.max_age <= 80 &&
        form.min_age <= 80
      );
    if (stepId === "tags") return (form.tags || []).length >= MIN_INTEREST_TAGS;
    return true;
  }, [form, stepId]);

  function next() {
    const validationErrors: string[] = [];
    setError("");
    if (stepId === "name" && !form.name.trim()) validationErrors.push("name_required");
    if (stepId === "gender" && !form.gender) validationErrors.push("gender_required");
    if (stepId === "dob") {
      const age = ageFromIsoUtc(form.date_of_birth);
      if (age == null) {
        validationErrors.push("dob_incomplete");
      }
      if (age != null && age < 18) {
        validationErrors.push("dob_under18");
      }
    }
    if (stepId === "city" && !form.city.trim()) {
      validationErrors.push("city_required");
    }
    if (stepId === "photos" && form.photos.length === 0) {
      validationErrors.push("photo_required");
    }
    if (stepId === "languages") {
      if (!String(form.native_language || "").trim()) {
        validationErrors.push("native_language_required");
      }
    }
    if (stepId === "intent") {
      if (!form.looking_for) validationErrors.push("looking_for_required");
      if (!form.vibe) validationErrors.push("vibe_required");
      if (!form.interested_in) validationErrors.push("interested_in_required");
      if (form.min_age < 18) validationErrors.push("min_age_too_low");
      if (form.min_age > 80) validationErrors.push("min_age_too_high");
      if (form.max_age > 80) validationErrors.push("max_age_too_high");
      if (form.max_age < form.min_age) validationErrors.push("age_range_invalid");
    }
    if (stepId === "tags") {
      if ((form.tags || []).length < MIN_INTEREST_TAGS) {
        validationErrors.push("tags_min");
      }
    }
    // eslint-disable-next-line no-console
    console.log("[onboarding:next]", { step, stepKey: stepId, form, validationErrors });
    if (validationErrors.length) {
      if (validationErrors.includes("dob_incomplete")) {
        setError(t("onboarding.dob.error.incomplete"));
        return;
      }
      if (validationErrors.includes("dob_under18")) {
        setError(t("onboarding.dob.error.under18"));
        return;
      }
      if (validationErrors.includes("city_required")) {
        setError(t("onboarding.errors.cityRequired"));
        return;
      }
      if (validationErrors.includes("photo_required")) {
        setError(t("onboarding.errors.photoRequired"));
        return;
      }
      if (validationErrors.includes("native_language_required")) {
        setError(t("onboarding.languages.nativePlaceholder"));
        return;
      }
      if (validationErrors.includes("tags_min")) {
        setError(t("onboarding.tags.minPick", { n: MIN_INTEREST_TAGS }));
        return;
      }
      // Fallback: show the standard “save” error to avoid silent no-op.
      setError(t("onboarding.errors.save"));
      return;
    }
    setStep((s) => Math.min(s + 1, steps.length - 1));
  }

  function back() {
    setError("");
    setStep((s) => Math.max(0, s - 1));
  }

  async function finish() {
    setError("");
    if (saving) return;
    setSaving(true);
    try {
      if (form.photos.length < 1) {
        setStep(steps.indexOf("photos"));
        setError(t("onboarding.errors.photoRequired"));
        return;
      }
      if ((form.tags || []).length < MIN_INTEREST_TAGS) {
        setStep(steps.indexOf("tags"));
        setError(t("onboarding.tags.minPick", { n: MIN_INTEREST_TAGS }));
        return;
      }
      const payload = {
        display_name: form.name.trim(),
        gender: form.gender || undefined,
        date_of_birth: form.date_of_birth || undefined,
        city: form.city.trim() || undefined,
        native_language: String(form.native_language || locale || "").trim() || undefined,
        additional_languages: (form.additional_languages || []).join(","),
        relationship_goal: form.looking_for || undefined,
        vibe: form.vibe || undefined,
        interested_in: form.interested_in || undefined,
        min_preferred_age: Math.trunc(Number(form.min_age)),
        max_preferred_age: Math.trunc(Number(form.max_age)),
        interests: (form.tags || []).join(","),
        photo_urls: photoUrlsForApi(form.photos, form.primaryIndex),
        onboarding_completed: true,
      };
      const saved = (await apiFetch("/profiles/me", {
        method: "PATCH",
        body: JSON.stringify(payload),
        metaReason: "onboarding-tinder-finish",
        skipThrottle: true,
        skipCache: true,
      })) as { onboarding_completed?: boolean };

      const completed = Boolean(saved && typeof saved === "object" && saved.onboarding_completed);
      if (completed) {
        markOnboardingCompletedTimestamp();
        void trackAnalyticsEvent("onboarding_completed", { source: "onboarding" });
        try {
          sessionStorage.removeItem(ONBOARDING_DRAFT_KEY);
        } catch {
          /* ignore */
        }
        invalidateAuthBootstrapCache();
        const me = await apiFetch("/auth/me", {
          method: "GET",
          metaReason: "onboarding-after-save",
          skipThrottle: true,
          skipCache: true,
        });
        primeAuthBootstrapFromMe(me);
        applyAuthBootstrapResult({ status: "ok", me });
        invalidateApiGetCache("/profiles/me");
        // eslint-disable-next-line no-console
        console.log("[neyra:onboarding] save result", {
          onboarding_completed: saved.onboarding_completed,
          step,
          redirecting: true,
        });
        router.replace("/discover");
        return;
      }

      invalidateAuthBootstrapCache();
      const meRetry = await apiFetch("/auth/me", {
        method: "GET",
        metaReason: "onboarding-auth-refresh",
        skipThrottle: true,
        skipCache: true,
      });
      primeAuthBootstrapFromMe(meRetry);
      applyAuthBootstrapResult({ status: "ok", me: meRetry });
      const onboardingRequired = Boolean(
        meRetry && typeof meRetry === "object" ? (meRetry as { onboarding_required?: boolean }).onboarding_required : true,
      );
      if (!onboardingRequired) {
        markOnboardingCompletedTimestamp();
        try {
          sessionStorage.removeItem(ONBOARDING_DRAFT_KEY);
        } catch {
          /* ignore */
        }
        invalidateApiGetCache("/profiles/me");
        router.replace("/discover");
        return;
      }
      setError(t("onboarding.errors.save"));
    } catch (e) {
      // eslint-disable-next-line no-console
      console.log("[onboarding] finish save failed", e);
      setError(t("onboarding.errors.save"));
    } finally {
      setSaving(false);
    }
  }

  if (booting) {
    return (
      <PageShell>
        <div className="auth-boot-loading" aria-busy="true" aria-live="polite" style={{ minHeight: "42vh", padding: 24 }} />
      </PageShell>
    );
  }

  return (
    <PageShell>
      <div style={{ maxWidth: 720, margin: "0 auto", width: "100%", padding: "12px 14px 0" }}>
        <FirstImpressionIntro variant="compact" />
      </div>
      <div style={{ maxWidth: 720, margin: "0 auto", width: "100%", padding: "18px 14px 6px" }}>
        <div className="h2" style={{ fontSize: 26, letterSpacing: "-0.04em", fontWeight: 900 }}>
          {t("onboarding.header.title")}
        </div>
        <div className="caption" style={{ opacity: 0.7, marginTop: 6 }}>
          {t("onboarding.header.step", { current: step + 1, total: steps.length })} ({stepId})
        </div>
        <div style={{ marginTop: 12 }}>
          <div style={{ height: 10, borderRadius: 999, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
            <div
              style={{
                height: "100%",
                width: `${Math.round(((step + 1) / steps.length) * 100)}%`,
                background: "rgba(180,120,255,0.85)",
                transition: "width 220ms ease",
              }}
            />
          </div>
        </div>
        {error ? (
          <div className="caption" style={{ marginTop: 10, color: "rgba(255,140,140,0.95)" }}>
            {error}
          </div>
        ) : null}
      </div>

      <div className="grid" style={{ maxWidth: 720, margin: "0 auto", width: "100%" }}>
        {step >= 3 ? (
          <Card className="surface" style={{ padding: 16 }}>
            <div className="caption" style={{ opacity: 0.8, fontWeight: 700 }}>
              {t("onboarding.preview.title")}
            </div>
            <div className="caption" style={{ marginTop: 6, opacity: 0.85, lineHeight: 1.35 }}>
              {t("onboarding.preview.hook3x")}
            </div>
            <div style={{ marginTop: 12, display: "flex", gap: 12, alignItems: "center" }}>
              <div style={{ width: 56, height: 56, borderRadius: 16, overflow: "hidden", background: "rgba(255,255,255,0.06)" }}>
                <SafeImg
                  src={previewPhoto || null}
                  alt=""
                  style={{ width: "100%", height: "100%", objectFit: "cover" }}
                  loading="lazy"
                  previewUnavailableText={t("photos.previewUnavailable")}
                />
              </div>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontWeight: 900, fontSize: 18, lineHeight: 1.15 }}>
                  {(form.name || t("discover.card.aiNameFallback")).trim()}
                  {derivedAge != null ? `, ${derivedAge}` : ""}
                </div>
                <div className="caption" style={{ opacity: 0.82, marginTop: 4 }}>
                  {(form.city || t("onboarding.profile.cityPlaceholder")).trim()}
                </div>
                {topTags.length ? (
                  <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 8 }}>
                    {topTags.map((tag) => (
                      <span
                        key={tag}
                        className="chip"
                        style={{
                          padding: "6px 10px",
                          borderRadius: 999,
                          border: "1px solid rgba(255,255,255,0.14)",
                          background: "rgba(255,255,255,0.06)",
                          color: "rgba(255,255,255,0.95)",
                          fontSize: 13,
                        }}
                      >
                        {t(`profile.interests.${tag}`)}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          </Card>
        ) : null}

        {stepId === "name" ? (
          <Card className="surface" style={{ padding: 18 }}>
            <div className="h2" style={{ fontSize: 22, fontWeight: 900 }}>
              {t("onboarding.name")}
            </div>
            <div style={{ marginTop: 12 }}>
              <Input
                autoFocus
                value={form.name}
                onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
                placeholder={t("auth.common.displayName")}
              />
            </div>
            <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end" }}>
              <Button type="button" onClick={next} disabled={!canNext}>
                {t("onboarding.next")}
              </Button>
            </div>
          </Card>
        ) : null}

        {stepId === "gender" ? (
          <Card className="surface" style={{ padding: 18 }}>
            <div className="h2" style={{ fontSize: 22, fontWeight: 900 }}>
              {t("onboarding.gender.title")}
            </div>
            <div style={{ marginTop: 14, display: "grid", gap: 10 }}>
              <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
                <Button type="button" variant={form.gender === "man" ? "primary" : "secondary"} onClick={() => setForm((p) => ({ ...p, gender: "man" }))}>
                  {t("onboarding.gender.man")}
                </Button>
                <Button type="button" variant={form.gender === "woman" ? "primary" : "secondary"} onClick={() => setForm((p) => ({ ...p, gender: "woman" }))}>
                  {t("onboarding.gender.woman")}
                </Button>
              </div>
            </div>

            <div style={{ marginTop: 16, display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
              <Button type="button" variant="secondary" onClick={back}>
                {t("onboarding.back")}
              </Button>
              <Button type="button" onClick={next} disabled={!canNext}>
                {t("onboarding.next")}
              </Button>
            </div>
          </Card>
        ) : null}

        {stepId === "dob" ? (
          <Card className="surface" style={{ padding: 18 }}>
            <div className="h2" style={{ fontSize: 22, fontWeight: 900 }}>
              {t("onboarding.dob.title")}
            </div>
            <div className="subtitle" style={{ marginTop: 8, opacity: 0.85 }}>
              {t("onboarding.dob.subtitle")}
            </div>
            <div style={{ marginTop: 12 }}>
              <OnboardingDobFields
                value={form.date_of_birth}
                onChange={(iso) => setForm((p) => ({ ...p, date_of_birth: iso }))}
                locale={locale}
                t={t}
              />
            </div>

            <div style={{ marginTop: 16, display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
              <Button type="button" variant="secondary" onClick={back}>
                {t("onboarding.back")}
              </Button>
              <Button type="button" onClick={next} disabled={!canNext}>
                {t("onboarding.next")}
              </Button>
            </div>
          </Card>
        ) : null}

        {stepId === "city" ? (
          <Card className="surface" style={{ padding: 18 }}>
            <div className="h2" style={{ fontSize: 22, fontWeight: 900 }}>
              {t("onboarding.city.title")}
            </div>
            <div className="subtitle" style={{ marginTop: 8, opacity: 0.85 }}>
              {t("onboarding.city.subtitle")} {t("onboarding.preview.hook3x")}
            </div>
            <div style={{ marginTop: 12 }}>
              <Input
                autoFocus
                value={form.city}
                onChange={(e) => setForm((p) => ({ ...p, city: e.target.value }))}
                placeholder={t("onboarding.city.placeholder")}
              />
            </div>
            <div style={{ marginTop: 16, display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
              <Button type="button" variant="secondary" onClick={back}>
                {t("onboarding.back")}
              </Button>
              <Button type="button" onClick={next} disabled={!canNext}>
                {t("onboarding.next")}
              </Button>
            </div>
          </Card>
        ) : null}

        {stepId === "photos" ? (
          <Card className="surface" style={{ padding: 18 }}>
            <div className="h2" style={{ fontSize: 22, fontWeight: 900 }}>
              {t("onboarding.photos.title")}
            </div>
            <div className="subtitle" style={{ marginTop: 8, opacity: 0.85 }}>
              {t("onboarding.photos.subtitle")}
            </div>
            <div style={{ marginTop: 14 }}>
              <PhotoUploader
                urls={form.photos}
                primaryIndex={form.primaryIndex}
                disabled={false}
                onChange={(urls, idx) => {
                  const cleaned = (urls || []).map((u) => String(u || "").trim()).filter(Boolean);
                  setForm((p) => ({
                    ...p,
                    photos: cleaned,
                    primaryIndex: Math.max(0, Math.min(cleaned.length - 1, Math.trunc(Number(idx ?? 0)))),
                  }));
                }}
                onError={(msg: NonNullable<I18nText>) => setError(resolveI18nText(msg, t))}
              />
            </div>

            <div style={{ marginTop: 16, display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
              <Button type="button" variant="secondary" onClick={back}>
                {t("onboarding.back")}
              </Button>
              <Button type="button" onClick={next} disabled={!canNext}>
                {t("onboarding.next")}
              </Button>
            </div>
          </Card>
        ) : null}

        {stepId === "languages" ? (
          <Card className="surface" style={{ padding: 18 }}>
            <div className="h2" style={{ fontSize: 22, fontWeight: 900 }}>
              {t("onboarding.languages.title")}
            </div>
            <div className="subtitle" style={{ marginTop: 8, opacity: 0.85, lineHeight: 1.35 }}>
              {t("onboarding.languages.subtitle")}
            </div>

            <div style={{ marginTop: 14 }}>
              <div className="caption" style={{ opacity: 0.9, fontWeight: 700 }}>
                {t("onboarding.languages.nativeTitle")}
              </div>
              <div className="subtitle" style={{ marginTop: 6, opacity: 0.82, lineHeight: 1.35 }}>
                {t("onboarding.languages.nativeLabel")}
              </div>
              <div style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 8 }}>
                {sortLocalesForSelect(locale as AppLocale, LOCALES.map((l) => l.code)).map((code) => {
                  const row = LOCALES.find((l) => l.code === code);
                  const selected = String(form.native_language || "").trim() === code;
                  return (
                    <button
                      key={code}
                      type="button"
                      className="chip"
                      style={{
                        padding: "8px 12px",
                        borderRadius: 999,
                        border: "1px solid rgba(255,255,255,0.14)",
                        background: selected ? "rgba(180,120,255,0.22)" : "rgba(255,255,255,0.06)",
                        color: "rgba(255,255,255,0.95)",
                        cursor: "pointer",
                      }}
                      onClick={() => setForm((p) => ({ ...p, native_language: code }))}
                    >
                      <span aria-hidden>{row?.flag} </span>
                      {row?.label}
                      {selected ? " ✓" : ""}
                    </button>
                  );
                })}
              </div>
            </div>

            <div style={{ marginTop: 16 }}>
              <div className="caption" style={{ opacity: 0.9, fontWeight: 700 }}>
                {t("onboarding.languages.additionalTitle")}
              </div>
              <div className="subtitle" style={{ marginTop: 6, opacity: 0.82, lineHeight: 1.35 }}>
                {t("onboarding.languages.additionalHint")}
              </div>
              <div style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 8 }}>
                {extraLangOptions
                  .filter((code) => code !== String(form.native_language || "").trim())
                  .map((code) => {
                    const row = LOCALES.find((l) => l.code === code);
                    const selected = (form.additional_languages || []).includes(code);
                    return (
                      <button
                        key={code}
                        type="button"
                        className="chip"
                        style={{
                          padding: "8px 12px",
                          borderRadius: 999,
                          border: "1px solid rgba(255,255,255,0.14)",
                          background: selected ? "rgba(124,92,255,0.22)" : "rgba(255,255,255,0.06)",
                          color: "rgba(255,255,255,0.95)",
                          cursor: "pointer",
                        }}
                        onClick={() => {
                          setForm((p) => {
                            const cur = p.additional_languages || [];
                            const has = cur.includes(code);
                            if (has) return { ...p, additional_languages: cur.filter((x) => x !== code) };
                            if (cur.length >= 5) return p;
                            return { ...p, additional_languages: [...cur, code] };
                          });
                        }}
                      >
                        <span aria-hidden>{row?.flag} </span>
                        {row?.label}
                        {selected ? " ✓" : ""}
                      </button>
                    );
                  })}
              </div>
            </div>

            <div style={{ marginTop: 16, display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
              <Button type="button" variant="secondary" onClick={back}>
                {t("onboarding.back")}
              </Button>
              <Button type="button" onClick={next} disabled={!canNext}>
                {t("onboarding.next")}
              </Button>
            </div>
          </Card>
        ) : null}

        {stepId === "intent" ? (
          <Card className="surface" style={{ padding: 18 }}>
            <div className="h2" style={{ fontSize: 22, fontWeight: 900 }}>
              {t("onboarding.intent.title")}
            </div>
            <div className="subtitle" style={{ marginTop: 8, opacity: 0.85, lineHeight: 1.35 }}>
              {t("onboarding.intent.combinedHint")}
            </div>
            <div style={{ marginTop: 12, display: "grid", gap: 12 }}>
              <label style={{ display: "grid", gap: 6 }}>
                <div className="caption">{t("onboarding.preferences.lookingForTitle")}</div>
                <select className="input" value={form.looking_for} onChange={(e) => setForm((p) => ({ ...p, looking_for: String(e.target.value || "") }))}>
                  <option value="">{t("common.none")}</option>
                  <option value="dating">{t("goals.dating")}</option>
                  <option value="relationship">{t("goals.relationship")}</option>
                  <option value="chat">{t("goals.chat")}</option>
                </select>
              </label>
              <label style={{ display: "grid", gap: 6 }}>
                <div className="caption">{t("onboarding.intent.vibeTitle")}</div>
                <select className="input" value={form.vibe} onChange={(e) => setForm((p) => ({ ...p, vibe: String(e.target.value || "") }))}>
                  <option value="">{t("common.none")}</option>
                  <option value="warm">{t("onboarding.intent.vibe.warm")}</option>
                  <option value="playful">{t("onboarding.intent.vibe.playful")}</option>
                  <option value="grounded">{t("onboarding.intent.vibe.grounded")}</option>
                  <option value="creative">{t("onboarding.intent.vibe.creative")}</option>
                  <option value="adventurous">{t("onboarding.intent.vibe.adventurous")}</option>
                </select>
              </label>
              <label style={{ display: "grid", gap: 6 }}>
                <div className="caption">{t("onboarding.preferences.interestedInTitle")}</div>
                <select className="input" value={form.interested_in} onChange={(e) => setForm((p) => ({ ...p, interested_in: String(e.target.value || "") }))}>
                  <option value="">{t("common.none")}</option>
                  <option value="men">{t("onboarding.preference.men")}</option>
                  <option value="women">{t("onboarding.preference.women")}</option>
                  <option value="everyone">{t("onboarding.preferences.interestedIn.everyone")}</option>
                </select>
              </label>

              <div style={{ display: "grid", gap: 10 }}>
                <div className="caption">{t("onboarding.preferences.ageRange")}</div>
                <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
                  <label style={{ display: "grid", gap: 6 }}>
                    <div className="caption" style={{ opacity: 0.8 }}>
                      {t("onboarding.preferences.minAge")}
                    </div>
                    <select
                      className="input"
                      value={String(form.min_age)}
                      onChange={(e) => {
                        const v = Math.max(18, Math.min(80, Math.trunc(Number(e.target.value || 18))));
                        setForm((p) => ({ ...p, min_age: v, max_age: Math.max(v, Math.min(80, p.max_age)) }));
                      }}
                    >
                      {Array.from({ length: 63 }, (_, i) => 18 + i).map((n) => (
                        <option key={n} value={String(n)}>
                          {n}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label style={{ display: "grid", gap: 6 }}>
                    <div className="caption" style={{ opacity: 0.8 }}>
                      {t("onboarding.preferences.maxAge")}
                    </div>
                    <select
                      className="input"
                      value={String(form.max_age)}
                      onChange={(e) => {
                        const v = Math.max(18, Math.min(80, Math.trunc(Number(e.target.value || 35))));
                        setForm((p) => ({ ...p, max_age: Math.max(p.min_age, v) }));
                      }}
                    >
                      {Array.from({ length: 63 }, (_, i) => 18 + i).map((n) => (
                        <option key={n} value={String(n)}>
                          {n}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </div>
            </div>
            <div style={{ marginTop: 16, display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
              <Button type="button" variant="secondary" onClick={back}>
                {t("onboarding.back")}
              </Button>
              <Button type="button" onClick={next} disabled={!canNext}>
                {t("onboarding.next")}
              </Button>
            </div>
          </Card>
        ) : null}

        {stepId === "tags" ? (
          <Card className="surface" style={{ padding: 18 }}>
            <div className="h2" style={{ fontSize: 22, fontWeight: 900 }}>
              {t("onboarding.tags.title")}
            </div>
            <div className="subtitle" style={{ marginTop: 8, opacity: 0.85 }}>
              {t("onboarding.tags.subtitle")} {t("onboarding.preview.hook3x")}
            </div>
            <div style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 10 }}>
              {(INTEREST_TAGS as readonly string[]).map((tag) => {
                const selected = (form.tags || []).includes(tag);
                return (
                  <button
                    key={tag}
                    type="button"
                    className="chip"
                    style={{
                      padding: "8px 12px",
                      borderRadius: 999,
                      border: "1px solid rgba(255,255,255,0.14)",
                      background: selected ? "rgba(180,120,255,0.22)" : "rgba(255,255,255,0.06)",
                      color: "rgba(255,255,255,0.95)",
                      cursor: "pointer",
                    }}
                    onClick={() => {
                      setForm((p) => {
                        const cur = p.tags || [];
                        const has = cur.includes(tag);
                        if (has) return { ...p, tags: cur.filter((x) => x !== tag) };
                        if (cur.length >= 10) return p;
                        return { ...p, tags: [...cur, tag] };
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
              {t("onboarding.tags.count", { count: (form.tags || []).length, max: 10 })}
            </div>
            <div style={{ marginTop: 16, display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
              <Button type="button" variant="secondary" onClick={back}>
                {t("onboarding.back")}
              </Button>
              <Button type="button" onClick={next} disabled={!canNext}>
                {t("onboarding.next")}
              </Button>
            </div>
          </Card>
        ) : null}

        {stepId === "done" ? (
          <Card className="surface" style={{ padding: 18 }}>
            <div className="h2" style={{ fontSize: 22, fontWeight: 900 }}>
              {t("onboarding.done.ready")}
            </div>
            <div className="subtitle" style={{ marginTop: 8, opacity: 0.85 }}>
              {t("onboarding.done.subtitle")}
            </div>
            <div style={{ marginTop: 16, display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
              <Button type="button" variant="secondary" onClick={back}>
                {t("onboarding.back")}
              </Button>
              <Button type="button" onClick={finish} disabled={saving}>
                {t("onboarding.done.cta")}
              </Button>
            </div>
          </Card>
        ) : null}
      </div>
    </PageShell>
  );
}
