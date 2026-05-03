"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiFetch, getToken } from "../../../lib/api";
import { i18nKey, resolveI18nText, type I18nText } from "../../../lib/i18n/message";
import { emitHookAttributionFromUrl, maybeEmitHookConverted } from "../../../lib/premiumPlusHookOptimization";
import { useT } from "../../components/i18n/I18nProvider";
import { PAGE_BOOT_FETCH_DELAY_MS, schedulePageLoad } from "../../../lib/pageLoad";
import { InviteFriendsCard } from "../../components/InviteFriendsCard";
import { PageHeader } from "../../components/PageHeader";
import { PageShell } from "../../components/PageShell";
import { Badge, Button, Card, Chip, Toast } from "../../components/ui";
import { fetchAbCopy, trackAbPremiumConversions, type AbCopyMap } from "../../../lib/abCopy";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { emitConversionAfterPurchase } from "../../../lib/paywallConversionHint";

export function SubscriptionPageFallback() {
  const { t } = useT("SubscriptionPage");
  return (
    <PageShell>
      <div data-testid="premium-modal" className="body muted" style={{ padding: 24 }}>
        {t("premium.modal.loading")}
      </div>
    </PageShell>
  );
}

export function SubscriptionPlansContent() {
  const { t } = useT("SubscriptionPage");
  const router = useRouter();
  const searchParams = useSearchParams();
  const showSupportBanner = String(searchParams.get("source") || "").toLowerCase() === "founder_welcome";
  const [data, setData] = useState<any>(null);
  const [toast, setToast] = useState<I18nText>(null);
  const bootStartedRef = useRef(false);
  const [checkoutState, setCheckoutState] = useState<{
    status: "idle" | "loading" | "succeeded" | "failed";
    planCode: "premium" | "premium_plus" | null;
    provider?: string | null;
    checkoutUrl?: string | null;
    activated?: boolean | null;
    message?: string | null;
  }>({ status: "idle", planCode: null });
  const checkoutInFlightRef = useRef(false);
  const paywallEntryTrackedRef = useRef(false);
  const postTrialPaywallShownRef = useRef(false);
  const paywallAttribRef = useRef({ source: null as string | null, segment: null as string | null, trigger: null as string | null });
  paywallAttribRef.current = {
    source: searchParams.get("source"),
    segment: searchParams.get("pw_segment"),
    trigger: searchParams.get("pw_trigger"),
  };
  const currentPlan = String(data?.plan_code || data?.plan || "free").toLowerCase();
  const stLow = String(data?.status || "").toLowerCase();
  const isActive = stLow === "active" || stLow === "past_due";
  const currentTier = currentPlan === "premium_plus" ? "premium_plus" : currentPlan === "premium" ? "premium" : "free";

  const plans = useMemo(() => {
    const free = {
      code: "free" as const,
      title: t("subscription.plan.free.title"),
      description: t("subscription.plan.free.description"),
      features: [
        t("subscription.plan.free.f.aiMatch"),
        t("subscription.plan.free.f.opener"),
        t("subscription.plan.free.f.rewrite"),
      ],
      price: t("subscription.price.free"),
    };
    const premium = {
      code: "premium" as const,
      title: t("subscription.plan.premium.title"),
      description: t("subscription.plan.premium.description"),
      features: [
        t("subscription.plan.premium.f.likes"),
        t("subscription.plan.premium.f.revealDaily"),
        t("subscription.plan.premium.f.swipes"),
        t("subscription.plan.premium.f.aiMatch"),
        t("subscription.plan.premium.f.openers"),
        t("subscription.plan.premium.f.rewrite"),
        t("subscription.plan.premium.f.readiness"),
        t("subscription.plan.premium.f.recovery"),
        t("subscription.plan.premium.f.escalation"),
      ],
      price: t("subscription.price.premium"),
    };
    const plus = {
      code: "premium_plus" as const,
      title: t("subscription.plan.plus.title"),
      description: t("subscription.plan.plus.description"),
      features: [
        t("subscription.plan.plus.f.unlimitedAi"),
        t("subscription.plan.plus.f.multiSuggestions"),
        t("subscription.plan.plus.f.bestReply"),
        t("subscription.plan.plus.f.deeperReasons"),
        t("subscription.plan.plus.f.morePersonal"),
        t("subscription.plan.plus.f.earlierEscalation"),
        t("subscription.plan.plus.f.likesPriority"),
      ],
      price: t("subscription.price.plus"),
    };
    return [free, premium, plus];
  }, [t]);

  const [abGrowth, setAbGrowth] = useState<AbCopyMap>({});

  useEffect(() => {
    void emitHookAttributionFromUrl();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    void fetchAbCopy([
      "subscription.pricing.copy",
      "growth.trial.duration",
      "paywall.message",
      "paywall.modal.copy",
      "ai.limit.copy",
    ]).then(setAbGrowth);
  }, []);

  useEffect(() => {
    if (paywallEntryTrackedRef.current) return;
    const { source, segment, trigger } = paywallAttribRef.current;
    const src = (source || "").toLowerCase();
    if (!segment && !trigger && !src.includes("soft_paywall")) return;
    paywallEntryTrackedRef.current = true;
    void trackAnalyticsEvent("paywall_subscription_entry", { source, pw_segment: segment, pw_trigger: trigger });
  }, [searchParams]);

  useEffect(() => {
    if (bootStartedRef.current) return;
    bootStartedRef.current = true;
    let cancelled = false;
    const cancelBootLoad = schedulePageLoad(() => {
      void apiFetch("/subscriptions/me", { metaReason: "subscription-page-open" })
        .then((nextData) => {
          if (!cancelled) setData(nextData);
          const plan = String((nextData as any)?.plan_code || (nextData as any)?.plan || "free").toLowerCase();
          const tier = plan === "premium_plus" ? "premium_plus" : plan === "premium" ? "premium" : "free";
          void maybeEmitHookConverted(tier as any);
        })
        .catch(() => {});
    }, PAGE_BOOT_FETCH_DELAY_MS);
    return () => {
      cancelled = true;
      bootStartedRef.current = false;
      cancelBootLoad();
    };
  }, []);

  const statusLine = useMemo(() => {
    if (!data) return undefined;
    const plan = String(data.plan_code || data.plan || "free").toLowerCase();
    const st = String(data.status || "").toLowerCase();
    if (plan === "premium_plus" && st === "active") return t("subscription.status.plusActive");
    if (plan === "premium" && st === "active") return t("subscription.status.premium");
    return t("subscription.status.free");
  }, [data, t]);

  async function refreshSubscription(reason: string) {
    try {
      const nextData = await apiFetch("/subscriptions/me", { metaReason: reason });
      setData(nextData);
      const plan = String((nextData as any)?.plan_code || (nextData as any)?.plan || "free").toLowerCase();
      const tier = plan === "premium_plus" ? "premium_plus" : plan === "premium" ? "premium" : "free";
      void maybeEmitHookConverted(tier as any);
      return nextData;
    } catch {
      return null;
    }
  }

  async function upgrade(planCode: "premium" | "premium_plus") {
    if (checkoutInFlightRef.current) return;
    checkoutInFlightRef.current = true;
    void trackAnalyticsEvent("paywall_cta_clicked", {
      cta_label: "upgrade",
      surface: "subscription_page",
      plan_code: planCode,
      current_tier: currentTier,
    });
    setCheckoutState({ status: "loading", planCode, provider: null, checkoutUrl: null, activated: null, message: null });
    void trackAnalyticsEvent("subscription_checkout_started", { plan_code: planCode, current_tier: currentTier });
    try {
      const result: any = await apiFetch("/subscriptions/checkout", {
        method: "POST",
        metaReason: "subscription-checkout",
        body: JSON.stringify({ plan_code: planCode }),
      });
      const provider = String(result?.provider || data?.provider || "").trim() || null;
      const checkoutUrl = String(result?.checkout_url || result?.checkout_url_hint || result?.checkoutUrl || result?.url || "").trim() || null;
      const activated = Boolean(result?.activated);

      setCheckoutState({
        status: "succeeded",
        planCode,
        provider,
        checkoutUrl,
        activated,
        message: activated ? t("subscription.checkout.success.activated") : t("subscription.checkout.success.created"),
      });
      const pa = paywallAttribRef.current;
      void trackAnalyticsEvent("subscription_checkout_succeeded", {
        plan_code: planCode,
        provider,
        activated,
        entry_source: pa.source,
        pw_segment: pa.segment,
        pw_trigger: pa.trigger,
      });

      const before = currentTier;
      const next = await refreshSubscription("subscription-checkout-refresh");
      const plan = String((next as any)?.plan_code || (next as any)?.plan || "free").toLowerCase();
      const st = String((next as any)?.status || "").toLowerCase();
      const after = plan === "premium_plus" ? "premium_plus" : plan === "premium" ? "premium" : "free";
      if (st === "active" && after !== before) {
        void trackAnalyticsEvent("subscription_plan_changed", { from: before, to: after, provider });
        if (after === "premium" || after === "premium_plus") {
          void trackAnalyticsEvent("premium_purchased", {
            from: before,
            to: after,
            provider,
            plan_code: planCode,
            channel: "subscription_page_checkout",
          });
          emitConversionAfterPurchase();
          trackAbPremiumConversions(abGrowth);
        }
      }

      setToast(i18nKey("subscription.checkout.created"));
      if (checkoutUrl) {
        if (typeof window !== "undefined" && provider && provider !== "mock") {
          window.location.assign(checkoutUrl);
        }
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setCheckoutState({ status: "failed", planCode, provider: null, checkoutUrl: null, activated: null, message: t("subscription.checkout.error.friendly") });
      void trackAnalyticsEvent("subscription_checkout_failed", { plan_code: planCode, error: message.slice(0, 240) });
      setToast(i18nKey("subscription.checkout.failed"));
    } finally {
      checkoutInFlightRef.current = false;
    }
  }

  const currentPlanLabel = useMemo(() => {
    if (currentTier === "premium_plus" && isActive) return t("subscription.current.plus");
    if (currentTier === "premium" && isActive) return t("subscription.current.premium");
    return t("subscription.current.free");
  }, [currentTier, isActive, t]);

  const trialExpiresRaw = data && typeof data === "object" ? String((data as { trial_expires_at?: unknown }).trial_expires_at || "").trim() : "";
  const trialActiveFlag = Boolean((data as { trial_active?: unknown })?.trial_active);
  const trialEndLabel = useMemo(() => {
    if (!trialExpiresRaw || !trialActiveFlag) return null;
    const d = new Date(trialExpiresRaw);
    if (Number.isNaN(d.getTime())) return null;
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }, [trialExpiresRaw, trialActiveFlag]);

  const [hadTrialEver, setHadTrialEver] = useState(false);
  useEffect(() => {
    try {
      setHadTrialEver(localStorage.getItem("neyra:growth_trial_ever") === "1");
    } catch {
      setHadTrialEver(false);
    }
  }, []);
  useEffect(() => {
    if (!trialActiveFlag || !trialExpiresRaw) return;
    try {
      localStorage.setItem("neyra:growth_trial_ever", "1");
      setHadTrialEver(true);
    } catch {
      /* ignore */
    }
  }, [trialActiveFlag, trialExpiresRaw]);

  useEffect(() => {
    if (currentTier !== "free") return;
    if (trialActiveFlag) return;
    if (!hadTrialEver) return;
    if (postTrialPaywallShownRef.current) return;
    postTrialPaywallShownRef.current = true;
    void trackAnalyticsEvent("paywall_shown", { surface: "post_trial_conversion", channel: "subscription_page" });
  }, [currentTier, trialActiveFlag, hadTrialEver]);

  const trialCountdown = useMemo(() => {
    if (!trialExpiresRaw || !trialActiveFlag) return null;
    const end = new Date(trialExpiresRaw);
    if (Number.isNaN(end.getTime())) return null;
    const ms = end.getTime() - Date.now();
    if (ms <= 0) return { kind: "ended" as const };
    const hours = ms / (60 * 60 * 1000);
    if (hours <= 24) return { kind: "soon" as const };
    const days = Math.max(1, Math.ceil(ms / (24 * 60 * 60 * 1000)));
    return { kind: "days" as const, days };
  }, [trialExpiresRaw, trialActiveFlag]);

  const isDev = typeof process !== "undefined" && process.env.NODE_ENV === "development";
  const paymentsProvider = String(data?.provider || "").trim().toLowerCase();
  const isMockPayments = paymentsProvider === "mock";

  const pricingVariantIdx = abGrowth["subscription.pricing.copy"]?.variant_index ?? 0;
  const showPricingPsychology = pricingVariantIdx !== 2;

  const selectedPlanTitle = useMemo(() => {
    const code = checkoutState.planCode;
    if (code === "premium_plus") return t("subscription.plan.plus.title");
    if (code === "premium") return t("subscription.plan.premium.title");
    return t("common.none");
  }, [checkoutState.planCode, t]);

  return (
    <>
      <div data-testid="premium-modal" style={{ display: "contents" }}>
      <PageShell>
        <PageHeader
          title={t("subscription.header.title")}
          subtitle={t("subscription.header.subtitle")}
          badge={<Badge tone="premium">{t("subscription.header.badge")}</Badge>}
          status={statusLine}
        />

        {currentTier === "free" ? (
          trialActiveFlag ? (
            <div
              className="body"
              style={{
                maxWidth: "72ch",
                margin: "0 auto 16px",
                padding: "12px 14px",
                borderRadius: 16,
                border: "1px solid rgba(124, 92, 255, 0.28)",
                background: "rgba(124, 92, 255, 0.09)",
                lineHeight: 1.45,
                opacity: 0.92,
              }}
            >
              <div>{t("subscription.trial.banner")}</div>
              {trialCountdown?.kind === "days" ? (
                <div className="caption" style={{ marginTop: 10, fontWeight: 700, opacity: 0.92 }}>
                  {t("growth.trial.endsInDays", { days: trialCountdown.days })}
                </div>
              ) : null}
              {trialCountdown?.kind === "soon" ? (
                <div className="caption" style={{ marginTop: 10, fontWeight: 750, opacity: 0.95 }}>
                  {t("growth.trial.expiresSoon")}
                </div>
              ) : null}
              {trialEndLabel ? (
                <div className="caption" style={{ marginTop: 10, opacity: 0.88 }}>
                  {t("subscription.trial.endsLine", { date: trialEndLabel })}
                </div>
              ) : null}
            </div>
          ) : hadTrialEver ? (
            <Card
              className="surface"
              style={{
                maxWidth: "72ch",
                margin: "0 auto 16px",
                padding: "14px 16px",
                borderRadius: 16,
                border: "1px solid rgba(255, 196, 108, 0.35)",
                background: "linear-gradient(145deg, rgba(255, 196, 108, 0.12), rgba(124, 92, 255, 0.08))",
              }}
            >
              <div className="h2" style={{ fontSize: 20, fontWeight: 900, margin: 0 }}>
                {t("growth.postTrial.headline")}
              </div>
              <div className="body" style={{ marginTop: 10, opacity: 0.9, lineHeight: 1.45 }}>
                {t("growth.postTrial.betterMatches")}
              </div>
              <ul className="body muted" style={{ margin: "12px 0 0", paddingLeft: "1.2rem", lineHeight: 1.5 }}>
                <li>{t("growth.postTrial.limitsAi")}</li>
                <li>{t("growth.postTrial.limitsLikes")}</li>
              </ul>
              <div style={{ marginTop: 14 }}>
                <Button
                  type="button"
                  onClick={() => {
                    void trackAnalyticsEvent("paywall_cta_clicked", {
                      cta_label: "restore_premium",
                      surface: "post_trial_card",
                      current_tier: currentTier,
                    });
                    document.getElementById("subscription-plans")?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }}
                >
                  {t("growth.postTrial.restoreCta")}
                </Button>
              </div>
            </Card>
          ) : (
            <div
              className="body"
              style={{
                maxWidth: "72ch",
                margin: "0 auto 16px",
                padding: "12px 14px",
                borderRadius: 16,
                border: "1px solid rgba(124, 92, 255, 0.28)",
                background: "rgba(124, 92, 255, 0.09)",
                lineHeight: 1.45,
                opacity: 0.92,
              }}
            >
              <div>{t("subscription.trial.banner")}</div>
            </div>
          )
        ) : null}

        {getToken() ? (
          <div style={{ maxWidth: "72ch", marginBottom: 12 }}>
            <InviteFriendsCard source="subscription_page" compact />
          </div>
        ) : null}

        {showSupportBanner ? (
          <Card className="surface" style={{ maxWidth: "72ch", marginBottom: 4 }}>
            <div className="section-label">{t("premium.support.title")}</div>
            <p className="body muted" style={{ margin: "10px 0 0", maxWidth: "62ch", whiteSpace: "pre-line" }}>
              {t("premium.support.body")}
            </p>
            <ul className="body muted" style={{ margin: "12px 0 0", paddingLeft: "1.25rem", maxWidth: "62ch" }}>
              <li style={{ marginBottom: 6 }}>{t("premium.support.point1")}</li>
              <li style={{ marginBottom: 6 }}>{t("premium.support.point2")}</li>
              <li>{t("premium.support.point3")}</li>
            </ul>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14 }}>
              <Button type="button" variant="secondary" onClick={() => document.getElementById("subscription-plans")?.scrollIntoView({ behavior: "smooth" })}>
                {t("premium.support.cta")}
              </Button>
              <Button type="button" variant="ghost" onClick={() => router.push("/invite?source=premium_support")}>
                {t("referrals.title")}
              </Button>
            </div>
          </Card>
        ) : null}

        <div className="grid grid-2">
          <Card className="surface">
            <div className="section-label">{t("subscription.features.eyebrow")}</div>
            <div>
              <Chip>{t("subscription.features.ai")}</Chip>
              <Chip>{t("subscription.features.compatibility")}</Chip>
              <Chip>{t("subscription.features.priority")}</Chip>
              <Chip>{t("subscription.features.coach")}</Chip>
            </div>
            <div style={{ height: 18 }} />
            <div className="body" style={{ maxWidth: "62ch" }}>
              <div style={{ display: "grid", gap: 8 }}>
                <div className="h2" style={{ margin: 0 }}>
                  {t("subscription.value.title")}
                </div>
                <div className="muted">{t("subscription.value.subtitle")}</div>
              </div>
              <div style={{ height: 14 }} />
              <div className="caption">{t("subscription.examples.eyebrow")}</div>
              <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
                <Card className="surface surface--inset" style={{ padding: 12 }}>
                  <div className="caption muted">{t("subscription.examples.ex1.label")}</div>
                  <div className="body">{t("subscription.examples.ex1.text")}</div>
                </Card>
                <Card className="surface surface--inset" style={{ padding: 12 }}>
                  <div className="caption muted">{t("subscription.examples.ex2.label")}</div>
                  <div className="body">{t("subscription.examples.ex2.text")}</div>
                </Card>
                <Card className="surface surface--inset" style={{ padding: 12 }}>
                  <div className="caption muted">{t("subscription.examples.ex3.label")}</div>
                  <div className="body">{t("subscription.examples.ex3.text")}</div>
                </Card>
              </div>
            </div>
            <div style={{ height: 18 }} />
            {checkoutState.status !== "idle" ? (
              <Card className="surface surface--inset" style={{ padding: 14 }}>
                <div className="section-label">{t("subscription.checkout.panel.title")}</div>
                <div className="body" style={{ marginTop: 6 }}>
                  {t("subscription.checkout.panel.selectedPlan", {
                    value: selectedPlanTitle.trim() ? selectedPlanTitle : t("common.emDash"),
                  })}
                </div>
                <div className="caption muted" style={{ marginTop: 6 }}>
                  {t("subscription.checkout.panel.priceHint")}
                </div>
                <div style={{ height: 10 }} />
                {checkoutState.status === "loading" ? (
                  <div className="body muted">{t("subscription.checkout.loading")}</div>
                ) : checkoutState.status === "failed" ? (
                  <div className="body">{checkoutState.message || t("subscription.checkout.error.friendly")}</div>
                ) : (
                  <div className="body">{checkoutState.message || t("subscription.checkout.success.created")}</div>
                )}

                {isDev && isMockPayments && checkoutState.status === "succeeded" ? (
                  <div className="caption muted" style={{ marginTop: 10 }}>
                    {t("subscription.checkout.mockNotice")}
                  </div>
                ) : null}
              </Card>
            ) : null}
            <div id="subscription-plans" style={{ display: "grid", gap: 14 }}>
              {plans.map((plan) => {
                const current = plan.code !== "free" && currentTier === plan.code && isActive;
                const isFree = plan.code === "free";
                const busy = checkoutState.status === "loading";
                return (
                  <Card
                    key={plan.code}
                    className="surface surface--inset"
                    style={{
                      borderColor: current ? "rgba(255, 196, 108, 0.6)" : undefined,
                      background: current ? "rgba(255, 196, 108, 0.08)" : undefined,
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                      <div style={{ display: "grid", gap: 2 }}>
                        <div className="section-label">{plan.title}</div>
                        <div className="caption muted">{plan.price}</div>
                        {plan.code === "premium_plus" && showPricingPsychology ? (
                          <>
                            <div className="caption" style={{ textDecoration: "line-through", opacity: 0.55, marginTop: 4 }}>
                              {t("subscription.pricing.anchorWas")}
                            </div>
                            <div className="caption" style={{ fontWeight: 800, opacity: 0.95, marginTop: 2 }}>
                              {t("subscription.pricing.saveYearlyLine")}
                            </div>
                          </>
                        ) : null}
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, justifyContent: "flex-end" }}>
                        {current ? <Badge tone="premium">{t("subscription.badge.current")}</Badge> : null}
                        {plan.code === "premium_plus" ? <Badge tone="premium">{t("subscription.badge.mostPopular")}</Badge> : null}
                        {plan.code === "premium_plus" && showPricingPsychology ? <Badge tone="premium">{t("subscription.badge.best")}</Badge> : null}
                      </div>
                    </div>
                    <div className="body muted" style={{ marginTop: 8 }}>
                      {plan.description}
                    </div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
                      {plan.features.map((feature) => (
                        <Chip key={feature}>{feature}</Chip>
                      ))}
                    </div>
                    <div style={{ marginTop: 14 }}>
                      {isFree ? (
                        <Button disabled variant="secondary">
                          {t("subscription.cta.free")}
                        </Button>
                      ) : (
                        <Button onClick={() => void upgrade(plan.code)} disabled={current || busy}>
                          {current ? t("subscription.cta.current") : t("subscription.cta.choose", { value: plan.title })}
                        </Button>
                      )}
                    </div>
                  </Card>
                );
              })}
            </div>
            <div style={{ height: 18 }} />
            <div className="section-label">{t("subscription.compare.title")}</div>
            <div className="caption muted" style={{ maxWidth: "64ch", marginTop: 6 }}>
              {t("subscription.compare.subtitle")}
            </div>
            <div style={{ height: 10 }} />
            <div style={{ overflowX: "auto" }} aria-label={t("subscription.compare.tableAria")}>
              <table className="table" style={{ width: "100%", borderCollapse: "separate", borderSpacing: 0 }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: "left", padding: "10px 12px" }}>{t("subscription.compare.col.feature")}</th>
                    <th style={{ textAlign: "left", padding: "10px 12px", whiteSpace: "nowrap" }}>{t("subscription.compare.col.free")}</th>
                    <th style={{ textAlign: "left", padding: "10px 12px", whiteSpace: "nowrap" }}>{t("subscription.compare.col.premium")}</th>
                    <th style={{ textAlign: "left", padding: "10px 12px", whiteSpace: "nowrap" }}>{t("subscription.compare.col.plus")}</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { label: t("subscription.compare.row.aiMatch"), free: "✓", premium: "✓", plus: "✓+" },
                    { label: t("subscription.compare.row.openers"), free: "—", premium: "✓", plus: "✓+" },
                    { label: t("subscription.compare.row.rewrite"), free: "—", premium: "✓", plus: "✓+" },
                    { label: t("subscription.compare.row.readiness"), free: "—", premium: "✓", plus: "✓+" },
                    { label: t("subscription.compare.row.recovery"), free: "—", premium: "✓", plus: "✓+" },
                    { label: t("subscription.compare.row.escalation"), free: "—", premium: "✓", plus: "✓+" },
                    { label: t("subscription.compare.row.deeperReasons"), free: "—", premium: "—", plus: "✓" },
                  ].map((r) => (
                    <tr key={r.label}>
                      <td style={{ padding: "10px 12px" }}>{r.label}</td>
                      <td style={{ padding: "10px 12px" }}>{r.free}</td>
                      <td style={{ padding: "10px 12px" }}>{r.premium}</td>
                      <td style={{ padding: "10px 12px" }}>{r.plus}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="caption" style={{ marginTop: 12, maxWidth: "42ch" }}>
              {t("subscription.caption")}
            </div>
          </Card>
          <Card className="surface surface--inset">
            <div className="section-label">{t("subscription.account.eyebrow")}</div>
            <h2 className="h2" style={{ marginBottom: 8 }}>
              {t("subscription.account.title")}
            </h2>
            <div className="body">{currentPlanLabel}</div>
            <div style={{ height: 16 }} />
            <div className="section-label">{t("subscription.checkout.latest")}</div>
            <div className="caption muted">
              {isDev && isMockPayments ? t("subscription.account.provider.mockDev") : t("subscription.account.provider.normal")}
            </div>
          </Card>
        </div>
      </PageShell>
      </div>
      <Toast text={resolveI18nText(toast, t)} onClose={() => setToast(null)} />
    </>
  );
}
