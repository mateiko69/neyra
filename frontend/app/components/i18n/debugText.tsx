"use client";

import type { ReactNode } from "react";
import { isI18nDebugEnabled, readI18nDebugMetadata } from "../../../lib/i18n";

export type I18nDebugStatus = "missing" | "raw" | null;

const rawStringWarnings = new Set<string>();

export function joinClassNames(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export function mergeI18nDebugStatus(...statuses: Array<I18nDebugStatus | undefined>): I18nDebugStatus {
  if (statuses.includes("missing")) return "missing";
  if (statuses.includes("raw")) return "raw";
  return null;
}

function looksSuspiciousRawString(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed) return false;
  if (trimmed.startsWith("[MISSING:")) return false;
  if (!/\p{L}/u.test(trimmed)) return false;
  if (/^https?:\/\//i.test(trimmed)) return false;
  if (/^[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}$/i.test(trimmed)) return false;
  if (/^[\d\s.,:+\-/%()]+$/u.test(trimmed)) return false;
  return true;
}

function warnSuspiciousRawString(component: string, prop: string, value: string) {
  const warningKey = `${component}:${prop}:${value}`;
  if (rawStringWarnings.has(warningKey)) return;
  rawStringWarnings.add(warningKey);
  console.warn(`[neyra:i18n] suspicious raw UI text in ${component}.${prop}: "${value}"`);
}

export function inspectI18nText(
  value: string | null | undefined,
  options: { component: string; prop: string; allowRaw?: boolean },
): {
  text: string;
  status: I18nDebugStatus;
  translated: boolean;
  missing: boolean;
  key?: string;
} {
  const meta = readI18nDebugMetadata(value);
  const text = meta?.text ?? (value ?? "");

  if (!isI18nDebugEnabled()) {
    return {
      text,
      status: null,
      translated: Boolean(meta),
      missing: Boolean(meta?.missing),
      key: meta?.key,
    };
  }

  if (meta?.missing) {
    return {
      text,
      status: "missing",
      translated: true,
      missing: true,
      key: meta.key,
    };
  }

  if (meta) {
    return {
      text,
      status: null,
      translated: true,
      missing: false,
      key: meta.key,
    };
  }

  if (!options.allowRaw && looksSuspiciousRawString(text)) {
    warnSuspiciousRawString(options.component, options.prop, text);
    return {
      text,
      status: "raw",
      translated: false,
      missing: false,
    };
  }

  return {
    text,
    status: null,
    translated: false,
    missing: false,
  };
}

export function getI18nDebugClassName(
  status: I18nDebugStatus,
  kind: "surface" | "field" = "surface",
): string {
  if (!status) return "";
  const base = kind === "field" ? "i18n-debug-field" : "i18n-debug-surface";
  return joinClassNames(base, `${base}--${status}`);
}

export function renderDebugText(
  value: ReactNode,
  options: { component: string; prop: string; allowRaw?: boolean },
): ReactNode {
  if (typeof value !== "string") return value;
  const inspected = inspectI18nText(value, options);
  if (!inspected.status) return inspected.text;
  return (
    <span
      className={joinClassNames("i18n-debug-text", `i18n-debug-text--${inspected.status}`)}
      data-i18n-debug={inspected.status}
    >
      {inspected.text}
    </span>
  );
}
