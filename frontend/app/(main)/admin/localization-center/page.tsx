"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../../../../lib/api";
import { LOCALES } from "../../../../lib/i18n/locales";
import { PageHeader } from "../../../components/PageHeader";
import { PageShell } from "../../../components/PageShell";
import { Badge, Button, Card, Skeleton } from "../../../components/ui";
import { useT } from "../../../components/i18n/I18nProvider";
import { translateApiUserMessage } from "../../../../lib/i18n/translateApiUserMessage";

type LocaleRow = {
  code: string;
  coverage: number;
  total_keys: number;
  translated_keys: number;
  missing: number;
  identical_to_en: number;
  raw_keys?: number;
  empty: number;
};

export default function AdminLocalizationCenterPage() {
  const { t } = useT("AdminLocalizationCenterPage");
  const [data, setData] = useState<{ locales: LocaleRow[]; generated_at?: string } | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState("");
  const [pick, setPick] = useState<string>("de");
  const [limit, setLimit] = useState<string>("80");

  const load = useCallback(async () => {
    setErr("");
    try {
      const res = await apiFetch("/admin/localization/coverage", {
        method: "GET",
        metaReason: "admin-l10n-center",
        skipThrottle: true,
      });
      setData(res);
    } catch (e: unknown) {
      const raw = e instanceof Error ? e.message : String(e);
      setErr(translateApiUserMessage(raw.trim(), t).trim() || t("admin.errors.generic"));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const byCode = useMemo(() => Object.fromEntries((data?.locales ?? []).map((r) => [r.code, r])), [data]);

  const statusFor = (row: LocaleRow): "ready" | "partial" | "broken" => {
    if (row.code === "en") return "ready";
    if (row.missing > 0 || row.empty > 0) return "broken";
    if (row.coverage < 92 || row.identical_to_en > 120) return "partial";
    return "ready";
  };

  const post = async (path: string, body?: Record<string, unknown>) => {
    setBusy(path);
    setToast("");
    try {
      await apiFetch(path, {
        method: "POST",
        body: JSON.stringify(body ?? {}),
        metaReason: "admin-l10n-action",
        skipThrottle: true,
      });
      setToast(t("admin.localizationCenter.msgDone"));
      await load();
    } catch (e: unknown) {
      const raw = e instanceof Error ? e.message : String(e);
      setToast(translateApiUserMessage(raw.trim(), t).trim() || t("admin.localizationCenter.msgErr"));
    } finally {
      setBusy(null);
    }
  };

  return (
    <PageShell>
      <PageHeader
        variant="section"
        title={t("admin.localizationCenter.title")}
        subtitle={err || t("admin.localizationCenter.subtitle")}
        badge={<Badge tone="streak">{t("admin.internal")}</Badge>}
        status={data?.generated_at ? data.generated_at : t("admin.localizationCoverage.statusLoading")}
      />

      <div style={{ marginBottom: 16 }}>
        <Link href="/admin" className="caption muted">
          {t("admin.localizationCenter.backAdmin")}
        </Link>
        {" · "}
        <Link href="/admin/localization-coverage" className="caption muted">
          {t("admin.localizationCenter.openCoverage")}
        </Link>
        {" · "}
        <Link href="/admin/localization-quality" className="caption muted">
          {t("admin.localizationCenter.openQuality")}
        </Link>
      </div>

      {toast ? (
        <p className="caption" style={{ marginBottom: 12 }}>
          {toast}
        </p>
      ) : null}

      <Card className="surface" style={{ marginBottom: 16, padding: 16 }}>
        <div className="section-label">{t("admin.hub.localizationTitle")}</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
          <Button type="button" variant="secondary" disabled={!!busy} onClick={() => post("/admin/localization-agent/scan")}>
            {t("admin.localizationCenter.runScan")}
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={!!busy}
            onClick={() => {
              if (typeof window !== "undefined" && !window.confirm(t("admin.localizationCenter.msgConfirmFix"))) return;
              void post("/admin/localization-agent/fix", { confirm: true, mode: "safe" });
            }}
          >
            {t("admin.localizationCenter.safeFix")}
          </Button>
        </div>
        <div style={{ marginTop: 16, display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <label className="caption">
            {t("admin.localizationCenter.promptLocale")}
            <input className="input" style={{ marginLeft: 8 }} value={pick} onChange={(e) => setPick(e.target.value.trim())} />
          </label>
          <label className="caption">
            {t("admin.localizationCenter.promptLimit")}
            <input className="input" style={{ marginLeft: 8, width: 80 }} value={limit} onChange={(e) => setLimit(e.target.value)} />
          </label>
          <Button
            type="button"
            disabled={!!busy || !pick}
            onClick={() =>
              post("/admin/localization/gemini/translate", {
                locales: pick,
                limit: Math.max(0, parseInt(limit, 10) || 0),
              })
            }
          >
            {t("admin.localizationCenter.geminiOne")}
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={!!busy}
            onClick={() =>
              post("/admin/localization/gemini/translate-all", {
                limit: Math.max(0, parseInt(limit, 10) || 0),
              })
            }
          >
            {t("admin.localizationCenter.geminiAll")}
          </Button>
        </div>
        <p className="caption muted" style={{ marginTop: 12 }}>
          {t("admin.localizationCenter.geminiNote")}
        </p>
      </Card>

      {!data ? (
        <Skeleton style={{ height: 240, borderRadius: 16 }} />
      ) : (
        <div className="grid grid-2" style={{ gap: 12 }}>
          {LOCALES.map((loc) => {
            const row = byCode[loc.code];
            if (!row) return null;
            const st = statusFor(row);
            const stLabel =
              st === "ready"
                ? t("admin.localizationCenter.statusReady")
                : st === "partial"
                  ? t("admin.localizationCenter.statusPartial")
                  : t("admin.localizationCenter.statusBroken");
            return (
              <Card key={loc.code} className="surface surface--inset" style={{ padding: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                  <div>
                    <strong>
                      {loc.flag} {loc.code}
                    </strong>
                    <div className="caption muted">{loc.labelEn}</div>
                  </div>
                  <Badge tone={st === "ready" ? "premium" : "streak"}>{stLabel}</Badge>
                </div>
                <div className="caption" style={{ marginTop: 10 }}>
                  {t("admin.localizationCenter.cardCoverage", { pct: row.coverage })}
                </div>
                <div className="caption">
                  {t("admin.localizationCenter.cardTranslated", { n: row.translated_keys, total: row.total_keys })}
                </div>
                <div className="caption">
                  {t("admin.localizationCenter.cardLeak", { n: row.identical_to_en })}
                  {loc.rtl ? ` · ${t("admin.localizationCenter.cardRtl")}` : ""}
                </div>
                <div className="caption muted">
                  {t("admin.localizationCenter.cardRaw", { n: row.raw_keys ?? 0 })} · {t("admin.localizationCenter.cardEmpty", { n: row.empty })}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </PageShell>
  );
}
