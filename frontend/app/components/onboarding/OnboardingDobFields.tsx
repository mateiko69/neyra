"use client";

import { useEffect, useMemo, useState } from "react";
import type { Locale } from "../../../lib/i18n";
import { INTL_LOCALE_BY_APP } from "../../../lib/i18n/locales";
import {
  ageFromIsoUtc,
  fromIsoDate,
  toIsoDate,
  useMonthDayYearFieldOrder,
} from "../../../lib/onboarding/dobIso";

type Translate = (key: string, vars?: Record<string, string | number>) => string;

type Tri = { d: number | ""; m: number | ""; y: number | "" };

type Props = {
  value: string;
  onChange: (isoYyyyMmDd: string) => void;
  locale: Locale;
  t: Translate;
};

function monthOptions(intlTag: string): { value: number; label: string }[] {
  return Array.from({ length: 12 }, (_, i) => {
    const monthIndex = i;
    const d = new Date(Date.UTC(2000, monthIndex, 1));
    const label = new Intl.DateTimeFormat(intlTag, { month: "long", timeZone: "UTC" }).format(d);
    return { value: monthIndex + 1, label };
  });
}

function triFromIso(iso: string): Tri {
  const p = fromIsoDate(iso);
  if (!p) return { d: "", m: "", y: "" };
  return { d: p.d, m: p.m, y: p.y };
}

export function OnboardingDobFields({ value, onChange, locale, t }: Props) {
  const mdy = useMonthDayYearFieldOrder(locale);
  const intlTag = INTL_LOCALE_BY_APP[locale] ?? "en";
  const months = useMemo(() => monthOptions(intlTag), [intlTag]);

  const [tri, setTri] = useState<Tri>(() => triFromIso(value));

  useEffect(() => {
    setTri(triFromIso(value));
  }, [value]);

  const yearChoices = useMemo(() => {
    const yMax = new Date().getUTCFullYear() - 18;
    const yMin = yMax - 82;
    const out: number[] = [];
    for (let y = yMax; y >= yMin; y -= 1) out.push(y);
    return out;
  }, []);

  function applyTri(next: Tri) {
    setTri(next);
    if (next.d === "" || next.m === "" || next.y === "") {
      onChange("");
      return;
    }
    const iso = toIsoDate(next.y, next.m, next.d);
    onChange(iso || "");
  }

  const daySelect = (
    <label style={{ display: "grid", gap: 6, minWidth: 0 }}>
      <span className="caption">{t("onboarding.dob.label.day")}</span>
      <select
        className="input"
        aria-label={t("onboarding.dob.label.day")}
        value={tri.d === "" ? "" : String(tri.d)}
        onChange={(e) => {
          const v = e.target.value === "" ? "" : Math.trunc(Number(e.target.value));
          applyTri({ ...tri, d: v === "" ? "" : v });
        }}
      >
        <option value="">{t("onboarding.dob.select")}</option>
        {Array.from({ length: 31 }, (_, i) => i + 1).map((d) => (
          <option key={d} value={String(d)}>
            {d}
          </option>
        ))}
      </select>
    </label>
  );

  const monthSelect = (
    <label style={{ display: "grid", gap: 6, minWidth: 0 }}>
      <span className="caption">{t("onboarding.dob.label.month")}</span>
      <select
        className="input"
        aria-label={t("onboarding.dob.label.month")}
        value={tri.m === "" ? "" : String(tri.m)}
        onChange={(e) => {
          const v = e.target.value === "" ? "" : Math.trunc(Number(e.target.value));
          applyTri({ ...tri, m: v === "" ? "" : v });
        }}
      >
        <option value="">{t("onboarding.dob.select")}</option>
        {months.map((m) => (
          <option key={m.value} value={String(m.value)}>
            {m.label}
          </option>
        ))}
      </select>
    </label>
  );

  const yearSelect = (
    <label style={{ display: "grid", gap: 6, minWidth: 0 }}>
      <span className="caption">{t("onboarding.dob.label.year")}</span>
      <select
        className="input"
        aria-label={t("onboarding.dob.label.year")}
        value={tri.y === "" ? "" : String(tri.y)}
        onChange={(e) => {
          const v = e.target.value === "" ? "" : Math.trunc(Number(e.target.value));
          applyTri({ ...tri, y: v === "" ? "" : v });
        }}
      >
        <option value="">{t("onboarding.dob.select")}</option>
        {yearChoices.map((y) => (
          <option key={y} value={String(y)}>
            {y}
          </option>
        ))}
      </select>
    </label>
  );

  const age = value ? ageFromIsoUtc(value) : null;
  const showUnder18 = age != null && age < 18;

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div
        style={{
          display: "grid",
          gap: 10,
          gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
        }}
      >
        {mdy ? (
          <>
            {monthSelect}
            {daySelect}
            {yearSelect}
          </>
        ) : (
          <>
            {daySelect}
            {monthSelect}
            {yearSelect}
          </>
        )}
      </div>
      <div className="caption" style={{ opacity: 0.75 }}>
        {mdy ? t("onboarding.dob.hint.mdy") : t("onboarding.dob.hint.dmy")}
      </div>
      {showUnder18 ? (
        <div className="caption" style={{ color: "rgba(255,140,140,0.95)" }}>
          {t("onboarding.dob.error.under18")}
        </div>
      ) : null}
    </div>
  );
}
