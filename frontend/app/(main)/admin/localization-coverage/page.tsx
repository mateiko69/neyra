"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../../../../lib/api";
import { PageHeader } from "../../../components/PageHeader";
import { PageShell } from "../../../components/PageShell";
import { Badge, Card, Skeleton } from "../../../components/ui";
import { useT } from "../../../components/i18n/I18nProvider";
import { translateApiUserMessage } from "../../../../lib/i18n/translateApiUserMessage";
import { LOCALES } from "../../../../lib/i18n/locales";

type LocaleRow = {
  code: string;
  coverage: number;
  coverage_present_pct?: number;
  total_keys: number;
  translated_keys: number;
  missing: number;
  identical_to_en: number;
  raw_keys?: number;
  empty: number;
  top_missing_keys: string[];
  top_identical_to_en_keys: string[];
  top_raw_key_values?: string[];
};

type CoverageSummary = {
  missing_keys_total?: number;
  raw_value_leaks_total?: number;
  en_fallback_keys_total?: number;
  unique_translated_keys_total?: number;
};

export default function AdminLocalizationCoveragePage() {
  const { t } = useT("AdminLocalizationCoveragePage");
  const [data, setData] = useState<{
    locales: LocaleRow[];
    generated_at?: string;
    summary?: CoverageSummary;
  } | null>(null);
  const [err, setErr] = useState<string>("");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const res = await apiFetch("/admin/localization/coverage", {
          method: "GET",
          metaReason: "admin-localization-coverage",
          skipThrottle: true,
        });
        setData(res);
      } catch (e: unknown) {
        const raw = e instanceof Error ? e.message : String(e);
        setErr(translateApiUserMessage(raw.trim(), t).trim() || t("admin.errors.generic"));
      }
    })();
  }, [t]);

  const flagByCode = useMemo(() => Object.fromEntries(LOCALES.map((l) => [l.code, l.flag])), []);
  const labelByCode = useMemo(() => Object.fromEntries(LOCALES.map((l) => [l.code, l.labelEn])), []);

  const rows = useMemo(() => {
    const list = Array.isArray(data?.locales) ? [...data.locales] : [];
    return list.sort((a, b) => {
      if (a.code === "en") return -1;
      if (b.code === "en") return 1;
      return (a.coverage ?? 0) - (b.coverage ?? 0);
    });
  }, [data]);

  const selectedRow = selected ? rows.find((r) => r.code === selected) : null;

  const summary = data?.summary;
  const nonEnRows = useMemo(() => rows.filter((r) => r.code !== "en"), [rows]);
  const avgUnique =
    nonEnRows.length > 0
      ? Math.round(nonEnRows.reduce((a, r) => a + (r.coverage ?? 0), 0) / nonEnRows.length)
      : 0;
  const avgPresent =
    nonEnRows.length > 0
      ? Math.round(
          nonEnRows.reduce((a, r) => a + (r.coverage_present_pct ?? r.coverage ?? 0), 0) / nonEnRows.length,
        )
      : 0;

  return (
    <PageShell>
      <PageHeader
        variant="section"
        title={t("admin.localizationCoverage.title")}
        subtitle={err ? err : t("admin.localizationCoverage.subtitle")}
        badge={<Badge tone="streak">{t("admin.internal")}</Badge>}
        status={data?.generated_at ? t("admin.localizationCoverage.statusUpdated", { at: data.generated_at }) : t("admin.localizationCoverage.statusLoading")}
      />

      <div style={{ marginBottom: 12 }}>
        <Link href="/admin/localization-quality" className="caption muted">
          {t("admin.localizationCoverage.linkQuality")}
        </Link>
      </div>

      {!data ? (
        <Skeleton style={{ height: 200, borderRadius: 20 }} />
      ) : (
        <Card className="surface">
          <div className="section-label">{t("admin.localization.section.languages")}</div>
          {summary ? (
            <p className="caption muted" style={{ marginTop: 8, maxWidth: "72ch" }}>
              {t("admin.localizationCoverage.catalogSummary", {
                missing: summary.missing_keys_total ?? 0,
                raw: summary.raw_value_leaks_total ?? 0,
                fallback: summary.en_fallback_keys_total ?? 0,
                avgUnique,
                avgPresent,
              })}
            </p>
          ) : null}
          <div style={{ marginTop: 12, overflowX: "auto" }}>
            <table className="caption" style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ textAlign: "left", borderBottom: "1px solid var(--border, #333)" }}>
                  <th style={{ padding: "8px 6px" }}>{t("admin.localization.table.locale")}</th>
                  <th style={{ padding: "8px 6px" }}>{t("admin.localization.table.coverage")}</th>
                  <th style={{ padding: "8px 6px" }}>{t("admin.localization.table.present")}</th>
                  <th style={{ padding: "8px 6px" }}>{t("admin.localization.table.translated")}</th>
                  <th style={{ padding: "8px 6px" }}>{t("admin.localization.table.missing")}</th>
                  <th style={{ padding: "8px 6px" }}>{t("admin.localization.table.raw")}</th>
                  <th style={{ padding: "8px 6px" }}>{t("admin.localizationCoverage.tableEqualsEn")}</th>
                  <th style={{ padding: "8px 6px" }}>{t("admin.localization.table.empty")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const pct = Math.max(0, Math.min(100, r.coverage ?? 0));
                  const pctPresent = Math.max(0, Math.min(100, r.coverage_present_pct ?? r.coverage ?? 0));
                  const active = selected === r.code;
                  return (
                    <tr
                      key={r.code}
                      onClick={() => setSelected(active ? null : r.code)}
                      style={{
                        cursor: "pointer",
                        background: active ? "rgba(127,127,127,0.12)" : undefined,
                        borderBottom: "1px solid rgba(127,127,127,0.08)",
                      }}
                    >
                      <td style={{ padding: "10px 6px", whiteSpace: "nowrap" }}>
                        <span style={{ marginRight: 8 }}>{flagByCode[r.code] ?? "🌐"}</span>
                        <strong>{r.code}</strong>
                        <span className="muted" style={{ marginLeft: 8 }}>
                          {labelByCode[r.code] ?? ""}
                        </span>
                      </td>
                      <td style={{ padding: "10px 6px", minWidth: 120 }}>
                        <div
                          style={{
                            height: 8,
                            borderRadius: 4,
                            background: "rgba(127,127,127,0.2)",
                            overflow: "hidden",
                          }}
                        >
                          <div
                            style={{
                              width: `${pct}%`,
                              height: "100%",
                              background: pct >= 80 ? "#3d9a5c" : pct >= 40 ? "#c9a227" : "#c44",
                            }}
                          />
                        </div>
                        <div style={{ marginTop: 4 }}>{pct}%</div>
                      </td>
                      <td style={{ padding: "10px 6px", minWidth: 120 }}>
                        <div
                          style={{
                            height: 8,
                            borderRadius: 4,
                            background: "rgba(127,127,127,0.2)",
                            overflow: "hidden",
                          }}
                        >
                          <div
                            style={{
                              width: `${pctPresent}%`,
                              height: "100%",
                              background: pctPresent >= 95 ? "#2a7a4a" : pctPresent >= 80 ? "#3d9a5c" : "#c9a227",
                            }}
                          />
                        </div>
                        <div style={{ marginTop: 4 }}>{pctPresent}%</div>
                      </td>
                      <td style={{ padding: "10px 6px" }}>{r.translated_keys}</td>
                      <td style={{ padding: "10px 6px" }}>{r.missing}</td>
                      <td style={{ padding: "10px 6px" }}>{r.raw_keys ?? 0}</td>
                      <td style={{ padding: "10px 6px" }}>{r.identical_to_en}</td>
                      <td style={{ padding: "10px 6px" }}>{r.empty}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="caption muted" style={{ marginTop: 12 }}>
            {t("admin.localizationCoverage.hintClickRow")}
          </p>
          {selectedRow ? (
            <div style={{ marginTop: 16 }}>
              <div className="section-label">
                {t("admin.localizationCoverage.detailsPrefix")} {selectedRow.code}
              </div>
              <pre
                className="caption"
                style={{ whiteSpace: "pre-wrap", marginTop: 8, maxHeight: 320, overflow: "auto" }}
              >
                {JSON.stringify(
                  {
                    top_missing_keys: selectedRow.top_missing_keys ?? [],
                    top_identical_to_en_keys: selectedRow.top_identical_to_en_keys ?? [],
                    top_raw_key_values: selectedRow.top_raw_key_values ?? [],
                  },
                  null,
                  2,
                )}
              </pre>
            </div>
          ) : null}
        </Card>
      )}
    </PageShell>
  );
}
