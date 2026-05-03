"use client";

import type { CSSProperties } from "react";
import { AI_DEBUG_ENABLED } from "../../lib/aiDebug";
import { useT } from "./i18n/I18nProvider";

type AiDebugPillProps = {
  label: string | null | undefined;
  style?: CSSProperties;
};

const baseStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "flex-start",
  gap: 8,
  padding: "8px 12px",
  borderRadius: 12,
  border: "1px dashed rgba(255, 152, 60, 0.65)",
  background: "rgba(18, 12, 6, 0.92)",
  color: "rgba(255, 214, 170, 0.92)",
  fontSize: 11,
  lineHeight: 1.35,
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
  boxShadow: "inset 0 0 0 1px rgba(255, 120, 40, 0.08)",
};

export function AiDebugPill({ label, style }: AiDebugPillProps) {
  if (!AI_DEBUG_ENABLED || !label) return null;
  const { t } = useT("AiDebugPill");
  return (
    <div data-ai-debug="true" style={{ ...baseStyle, ...style }}>
      <strong style={{ fontWeight: 800, letterSpacing: "0.04em", textTransform: "uppercase", color: "rgba(255, 176, 96, 0.95)" }}>
        {t("debug.dev")}
      </strong>
      <span style={{ flex: 1, minWidth: 0 }}>{label}</span>
    </div>
  );
}
