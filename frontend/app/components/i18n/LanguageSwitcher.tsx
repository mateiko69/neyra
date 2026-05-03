"use client";

import { useState } from "react";
import { getLocaleRow } from "../../../lib/i18n/locales";
import { useT } from "./I18nProvider";
import { LanguageModal } from "./LanguageModal";

type Props = {
  className?: string;
  /** Compact: flag only (e.g. mobile). */
  compact?: boolean;
};

export function LanguageSwitcher({ className = "", compact = false }: Props) {
  const { locale, t } = useT("LanguageSwitcher");
  const [open, setOpen] = useState(false);
  const row = getLocaleRow(locale);

  return (
    <>
      <button
        type="button"
        className={`language-switcher-pill nav-pill nav-pill-ghost nav-pill-quiet ${className}`.trim()}
        aria-label={t("languageSwitcher.aria")}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        <span className="language-switcher-pill__flag" aria-hidden>
          {row?.flag ?? "🌐"}
        </span>
        {compact ? null : <span className="language-switcher-pill__label">{row?.label ?? locale}</span>}
        <span className="language-switcher-pill__chev" aria-hidden>
          ▾
        </span>
      </button>
      <LanguageModal open={open} onClose={() => setOpen(false)} />
    </>
  );
}
