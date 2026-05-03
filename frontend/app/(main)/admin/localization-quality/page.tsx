"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../../../../lib/api";
import { PageHeader } from "../../../components/PageHeader";
import { PageShell } from "../../../components/PageShell";
import { Badge, Card, Chip, Skeleton } from "../../../components/ui";
import { useT } from "../../../components/i18n/I18nProvider";
import { translateApiUserMessage } from "../../../../lib/i18n/translateApiUserMessage";

export default function AdminLocalizationQualityPage() {
  const { t } = useT("AdminLocalizationQualityPage");
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<string>("");

  useEffect(() => {
    void (async () => {
      try {
        const res = await apiFetch("/admin/localization-quality", {
          method: "GET",
          metaReason: "admin-localization-quality",
          skipThrottle: true,
        });
        setData(res);
      } catch (e: unknown) {
        const raw = e instanceof Error ? e.message : String(e);
        setErr(translateApiUserMessage(raw.trim(), t).trim() || t("admin.errors.generic"));
      }
    })();
  }, [t]);

  const summary = data?.summary ?? {};
  const generatedAt = data?.generated_at ?? null;
  const missing = Boolean(data?.missing);
  const hardcoded: any[] = Array.isArray(data?.hardcoded_strings) ? data.hardcoded_strings : [];
  const promptIssues: any[] = Array.isArray(data?.prompt_issues) ? data.prompt_issues : [];
  const missingLocaleFiles: any[] = Array.isArray(data?.locales?.missing_locale_files) ? data.locales.missing_locale_files : [];
  const missingKeyLocales = useMemo(() => Object.keys(data?.locales?.missing_translation_keys ?? {}), [data]);

  return (
    <PageShell>
      <PageHeader
        variant="section"
        title={t("admin.localizationQuality.title")}
        subtitle={err ? err : t("admin.localizationQuality.subtitle")}
        badge={<Badge tone="streak">{t("admin.internal")}</Badge>}
        status={
          missing
            ? t("admin.localizationQuality.statusReportMissing")
            : generatedAt
              ? t("admin.localizationQuality.statusLastScan", { at: String(generatedAt) })
              : t("admin.localizationQuality.statusLoading")
        }
      />

      <div style={{ marginBottom: 12 }}>
        <Link href="/admin/localization-coverage" className="caption muted">
          {t("admin.localizationQuality.linkCoverage")}
        </Link>
      </div>

      {!data ? (
        <Skeleton style={{ height: 160, borderRadius: 20 }} />
      ) : (
        <>
          <div className="grid grid-2">
            <Card className="surface">
              <div className="section-label">{t("admin.lq.section.summary")}</div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                <Chip>
                  {t("admin.localizationQuality.chipMissingFiles", {
                    n: Number(summary?.missing_locale_files ?? missingLocaleFiles.length),
                  })}
                </Chip>
                <Chip>
                  {t("admin.localizationQuality.chipMissingKeys", {
                    n: Number(summary?.locales_missing_keys_locales ?? missingKeyLocales.length),
                  })}
                </Chip>
                <Chip>
                  {t("admin.localizationQuality.chipHardcoded", {
                    n: Number(summary?.hardcoded_strings ?? hardcoded.length),
                  })}
                </Chip>
                <Chip>
                  {t("admin.localizationQuality.chipPromptIssues", {
                    n: Number(summary?.prompt_issues ?? promptIssues.length),
                  })}
                </Chip>
              </div>
            </Card>
            <Card className="surface surface--inset">
              <div className="section-label">{t("admin.lq.section.report")}</div>
              <pre className="caption" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                {JSON.stringify({ generated_at: generatedAt, path: data?.path ?? null }, null, 2)}
              </pre>
            </Card>
          </div>

          <div style={{ height: 14 }} />

          <Card className="surface">
            <div className="section-label">{t("admin.lq.section.missingFiles")}</div>
            {!missingLocaleFiles.length ? (
              <div className="caption muted" style={{ marginTop: 8 }}>
                {t("admin.localizationQuality.ok")}
              </div>
            ) : (
              <pre className="caption" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                {JSON.stringify(missingLocaleFiles, null, 2)}
              </pre>
            )}
          </Card>

          <div style={{ height: 14 }} />

          <Card className="surface">
            <div className="section-label">{t("admin.lq.section.missingKeys")}</div>
            {!missingKeyLocales.length ? (
              <div className="caption muted" style={{ marginTop: 8 }}>
                {t("admin.localizationQuality.ok")}
              </div>
            ) : (
              <pre className="caption" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                {JSON.stringify(data?.locales?.missing_translation_keys ?? {}, null, 2)}
              </pre>
            )}
          </Card>

          <div style={{ height: 14 }} />

          <Card className="surface">
            <div className="section-label">{t("admin.lq.section.hardcoded")}</div>
            {!hardcoded.length ? (
              <div className="caption muted" style={{ marginTop: 8 }}>
                {t("admin.localizationQuality.ok")}
              </div>
            ) : (
              <pre className="caption" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                {JSON.stringify(hardcoded.slice(0, 60), null, 2)}
              </pre>
            )}
          </Card>

          <div style={{ height: 14 }} />

          <Card className="surface">
            <div className="section-label">{t("admin.lq.section.aiPrompts")}</div>
            {!promptIssues.length ? (
              <div className="caption muted" style={{ marginTop: 8 }}>
                {t("admin.localizationQuality.ok")}
              </div>
            ) : (
              <pre className="caption" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                {JSON.stringify(promptIssues, null, 2)}
              </pre>
            )}
          </Card>
        </>
      )}
    </PageShell>
  );
}

