"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "../../../lib/api";
import { fetchAbCopy, trackAbPremiumConversions, type AbCopyMap } from "../../../lib/abCopy";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { emitConversionAfterPurchase } from "../../../lib/paywallConversionHint";
import { useT } from "../i18n/I18nProvider";
import { Button } from "../ui";

export function PremiumUpgradeModal(props: {
  open: boolean;
  onClose: () => void;
  source: string;
}) {
  const { t } = useT("PremiumUpgradeModal");
  const router = useRouter();
  const [loading, setLoading] = useState<null | "monthly" | "yearly">(null);
  const onceRef = useRef(false);
  const shownAnalyticsRef = useRef(false);
  const [abModal, setAbModal] = useState<AbCopyMap>({});

  useEffect(() => {
    if (!props.open) return;
    void fetchAbCopy(["paywall.modal.copy", "paywall.message"]).then(setAbModal);
  }, [props.open]);

  useEffect(() => {
    if (!props.open) {
      shownAnalyticsRef.current = false;
      return;
    }
    if (shownAnalyticsRef.current) return;
    shownAnalyticsRef.current = true;
    void trackAnalyticsEvent("paywall_shown", { surface: "premium_upgrade_modal", source: props.source });
    void trackAnalyticsEvent("paywall_opened", {
      surface: "premium_upgrade_modal",
      entry_source: props.source,
    });
  }, [props.open, props.source]);

  if (!props.open) return null;

  async function checkout(plan: "premium" | "premium_plus", cadence: "monthly" | "yearly") {
    if (loading) return;
    void trackAnalyticsEvent("paywall_cta_clicked", {
      cta_label: cadence === "monthly" ? "upgrade_monthly" : "upgrade_yearly",
      surface: "premium_upgrade_modal",
      entry_source: props.source,
      checkout_plan: plan,
      checkout_cadence: cadence,
    });
    setLoading(cadence);
    try {
      // For now: map Monthly -> premium, Yearly -> premium_plus.
      await apiFetch("/subscriptions/checkout", {
        method: "POST",
        metaReason: `paywall-checkout:${props.source}:${cadence}`,
        body: JSON.stringify({ plan_code: plan }),
      });
      void trackAnalyticsEvent("upgrade_success", {
        surface: props.source,
        checkout_plan: plan,
        checkout_cadence: cadence,
      });
      void trackAnalyticsEvent("premium_purchased", {
        surface: props.source,
        checkout_plan: plan,
        checkout_cadence: cadence,
        channel: "premium_upgrade_modal",
      });
      emitConversionAfterPurchase();
      trackAbPremiumConversions(abModal);
      // Client-side nav (no full reload).
      router.push(`/premium?source=${encodeURIComponent(props.source)}`);
    } catch {
      if (!onceRef.current) {
        onceRef.current = true;
        router.push(`/premium?source=${encodeURIComponent(props.source)}`);
      }
    } finally {
      setLoading(null);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={props.onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 60,
        background: "rgba(0,0,0,0.62)",
        display: "grid",
        placeItems: "center",
        padding: 18,
      }}
    >
      <div
        className="surface"
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "100%",
          maxWidth: 420,
          borderRadius: 18,
          padding: 18,
          border: "1px solid rgba(255,255,255,0.14)",
          background: "rgba(20,18,24,0.96)",
        }}
      >
        <div className="h2" style={{ fontSize: 24, fontWeight: 950, letterSpacing: "-0.03em" }}>
          {t("premium.modal.title")}
        </div>
        <div className="subtitle" style={{ marginTop: 8, opacity: 0.85 }}>
          {(abModal["paywall.modal.copy"]?.text || "").trim() || t("premium.modal.subtitle")}
        </div>

        <ul className="caption" style={{ marginTop: 12, paddingLeft: "1.15rem", opacity: 0.9, lineHeight: 1.45, display: "grid", gap: 6 }}>
          <li>{t("premium.modal.benefit.1")}</li>
          <li>{t("premium.modal.benefit.2")}</li>
          <li>{t("premium.modal.benefit.3")}</li>
          <li>{t("premium.modal.benefit.4")}</li>
        </ul>
        <div className="caption" style={{ marginTop: 10, opacity: 0.78, lineHeight: 1.4 }}>
          {t("premium.modal.priceNote")}
        </div>

        <div style={{ marginTop: 14, display: "grid", gap: 10 }}>
          <Button type="button" disabled={loading != null} onClick={() => void checkout("premium", "monthly")}>
            {loading === "monthly" ? (
              t("premium.modal.loading")
            ) : (
              <span style={{ display: "grid", gap: 2, justifyItems: "center" }}>
                <span>{t("premium.modal.ctaContinue")}</span>
                <span className="caption" style={{ opacity: 0.82, fontWeight: 650 }}>
                  {t("subscription.price.premium")}
                </span>
              </span>
            )}
          </Button>
          <Button type="button" variant="secondary" disabled={loading != null} onClick={() => void checkout("premium_plus", "yearly")}>
            {loading === "yearly" ? (
              t("premium.modal.loading")
            ) : (
              <span style={{ display: "grid", gap: 2, justifyItems: "center" }}>
                <span>{t("premium.modal.ctaPlus")}</span>
                <span className="caption" style={{ opacity: 0.82, fontWeight: 650 }}>
                  {t("subscription.price.plus")}
                </span>
              </span>
            )}
          </Button>
          <Button type="button" variant="ghost" onClick={props.onClose} disabled={loading != null}>
            {t("common.notNow")}
          </Button>
        </div>
      </div>
    </div>
  );
}

