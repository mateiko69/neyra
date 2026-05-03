"use client";

/** Lightweight placeholder; shell chrome loads async — avoids blank first paint when needed. */
import { useT } from "./i18n/I18nProvider";

export function AppShellSkeleton() {
  const { t } = useT("AppShellSkeleton");
  return (
    <div
      className="neyra-shell-skeleton"
      aria-busy="true"
      aria-label={t("common.loading")}
      style={{
        minHeight: "48vh",
        padding: "24px 16px",
        maxWidth: 960,
        margin: "0 auto",
        display: "flex",
        flexDirection: "column",
        gap: 14,
      }}
    >
      <div style={{ height: 18, width: "38%", borderRadius: 8, background: "rgba(124, 92, 255, 0.12)" }} />
      <div style={{ height: 14, width: "72%", borderRadius: 8, background: "rgba(124, 92, 255, 0.08)" }} />
      <div style={{ height: 120, borderRadius: 16, background: "rgba(124, 92, 255, 0.06)" }} />
    </div>
  );
}
