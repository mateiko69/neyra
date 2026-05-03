"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, getToken, invalidateApiGetCache } from "../../../lib/api";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { i18nKey, resolveI18nText, type I18nText } from "../../../lib/i18n/message";
import { apiFailureToI18nText } from "../../../lib/i18n/translateApiUserMessage";
import { useT } from "../../components/i18n/I18nProvider";
import { PageHeader } from "../../components/PageHeader";
import { PageShell } from "../../components/PageShell";
import { Badge, Button, Card, Toast } from "../../components/ui";

export default function FounderWelcomePage() {
  const router = useRouter();
  const { t } = useT("FounderWelcomePage");
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<I18nText>(null);
  const [busy, setBusy] = useState(false);
  const checkedRef = useRef(false);

  useEffect(() => {
    if (checkedRef.current) return;
    checkedRef.current = true;
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    let cancelled = false;
    void apiFetch("/profiles/founder-welcome", { metaReason: "founder-welcome-status", skipThrottle: true })
      .then((data) => {
        if (cancelled) return;
        const show = Boolean(data && typeof data === "object" ? (data as any).show : false);
        if (!show) {
          router.replace("/discover");
          return;
        }
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  async function markSeen() {
    await apiFetch("/profiles/founder-welcome/seen", {
      method: "POST",
      body: JSON.stringify({}),
      skipThrottle: true,
      metaReason: "founder-welcome-seen",
    });
    invalidateApiGetCache("/auth/me");
    invalidateApiGetCache("/profiles/me");
  }

  async function continueToDiscover() {
    if (busy) return;
    setBusy(true);
    try {
      await markSeen();
      try {
        // Hide any invite-heavy surfaces for brand-new sessions.
        sessionStorage.setItem("neyra:hide_invite_until", String(Date.now() + 24 * 60 * 60 * 1000));
      } catch {
        /* ignore */
      }
      router.replace("/discover");
    } catch (error) {
      setToast(apiFailureToI18nText(error, t, "founder.error"));
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <PageShell>
        <Card className="surface" style={{ maxWidth: 760, margin: "0 auto" }}>
          <div className="body muted">{t("common.loading")}</div>
        </Card>
      </PageShell>
    );
  }

  return (
    <>
      <PageShell>
        <div className="grid" style={{ maxWidth: 820, margin: "0 auto", width: "100%" }}>
          <PageHeader
            variant="hero"
            title={t("founder.title")}
            subtitle={t("founder.clean.subtitle")}
            badge={<Badge>{t("founder.badge")}</Badge>}
          />

          <Card className="surface">
            <div className="section-label">{t("founder.clean.title")}</div>
            <p className="body" style={{ margin: "10px 0 0", maxWidth: "68ch", whiteSpace: "pre-line" }}>
              {t("founder.clean.body")}
            </p>

            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 20 }}>
              <Button type="button" onClick={() => void continueToDiscover()} disabled={busy}>
                {t("founder.clean.cta")}
              </Button>
            </div>
          </Card>
        </div>
      </PageShell>
      <Toast text={resolveI18nText(toast, t)} onClose={() => setToast(null)} />
    </>
  );
}
