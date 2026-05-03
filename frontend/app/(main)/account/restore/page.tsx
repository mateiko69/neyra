"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, clearAuth } from "../../../../lib/api";
import { i18nKey, resolveI18nText, type I18nText } from "../../../../lib/i18n/message";
import { useT } from "../../../components/i18n/I18nProvider";
import { PageHeader } from "../../../components/PageHeader";
import { PageShell } from "../../../components/PageShell";
import { Button, Card, Toast } from "../../../components/ui";

export default function AccountRestorePage() {
  const router = useRouter();
  const { t } = useT("AccountRestorePage");
  const [loading, setLoading] = useState(true);
  const [me, setMe] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<I18nText>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const authMe = await apiFetch("/auth/me", { method: "GET", skipAuthRedirect: true });
        if (cancelled) return;
        setMe(authMe);
      } catch {
        if (cancelled) return;
        setMe(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function restore() {
    if (busy) return;
    setBusy(true);
    setToast(null);
    try {
      await apiFetch("/account/restore", {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
        skipAuthRedirect: true,
      });
      const authMe = await apiFetch("/auth/me", { method: "GET", skipAuthRedirect: true });
      const onboardingRequired = Boolean(authMe?.onboarding_required);
      setToast(i18nKey("account.restore.success"));
      router.replace(onboardingRequired ? "/onboarding/fast" : "/discover");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.toLowerCase().includes("expired")) {
        setToast(i18nKey("account.restore.expired"));
      } else {
        setToast(i18nKey("account.restore.failed"));
      }
    } finally {
      setBusy(false);
    }
  }

  function signOut() {
    clearAuth();
    router.replace("/login");
  }

  const scheduledFor = String(me?.deletion_scheduled_for || "").trim();

  return (
    <>
      <PageShell>
        <PageHeader title={t("account.restore.title")} subtitle={t("account.restore.subtitle")} />
        <Card className="surface" style={{ padding: 18, maxWidth: 720 }}>
          {loading ? (
            <div className="body muted">{t("common.loading")}</div>
          ) : (
            <>
              <div className="body" style={{ maxWidth: "70ch" }}>
                {scheduledFor ? t("account.restore.detailWithDate", { value: scheduledFor }) : t("account.restore.detail")}
              </div>
              <div style={{ height: 14 }} />
              <div className="match-actions-row">
                <Button type="button" variant="primary" disabled={busy} onClick={() => void restore()}>
                  {busy ? t("common.working") : t("account.restore.cta")}
                </Button>
                <Button type="button" variant="ghost" disabled={busy} onClick={signOut}>
                  {t("account.restore.signOut")}
                </Button>
              </div>
            </>
          )}
        </Card>
      </PageShell>
      <Toast text={resolveI18nText(toast, t)} onClose={() => setToast(null)} />
    </>
  );
}

