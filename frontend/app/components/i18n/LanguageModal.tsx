"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Locale } from "../../../lib/i18n";
import { LOCALES, sortLocalesForSelect } from "../../../lib/i18n/locales";
import { useT } from "./I18nProvider";
import { Input } from "../ui";

type Props = {
  open: boolean;
  onClose: () => void;
};

export function LanguageModal({ open, onClose }: Props) {
  const { t, locale, setLocale } = useT("LanguageModal");
  const [q, setQ] = useState("");
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    setQ("");
    const id = window.requestAnimationFrame(() => {
      panelRef.current?.querySelector<HTMLInputElement>("#language-modal-search")?.focus();
    });
    return () => window.cancelAnimationFrame(id);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const ordered = sortLocalesForSelect(locale, LOCALES.map((l) => l.code));
    if (!needle) return ordered;
    return ordered.filter((code) => {
      const row = LOCALES.find((l) => l.code === code);
      if (!row) return false;
      return (
        row.label.toLowerCase().includes(needle) ||
        row.labelEn.toLowerCase().includes(needle) ||
        code.toLowerCase().includes(needle)
      );
    });
  }, [locale, q]);

  const pick = useCallback(
    (code: Locale) => {
      void Promise.resolve(setLocale(code)).then(() => {
        onClose();
      });
    },
    [onClose, setLocale],
  );

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div
      className="language-modal-backdrop"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        className="language-modal surface"
        role="dialog"
        aria-modal="true"
        aria-labelledby="language-modal-title"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="language-modal__head">
          <h2 id="language-modal-title" className="language-modal__title">
            {t("languageModal.title")}
          </h2>
          <button type="button" className="language-modal__close" onClick={onClose} aria-label={t("languageModal.close")}>
            ×
          </button>
        </div>
        <div className="language-modal__search">
          <Input
            id="language-modal-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("languageModal.searchPlaceholder")}
            aria-label={t("languageModal.searchPlaceholder")}
          />
        </div>
        <div className="language-modal__list" role="listbox" aria-label={t("languageModal.title")}>
          {filtered.map((code) => {
            const row = LOCALES.find((l) => l.code === code);
            if (!row) return null;
            const active = code === locale;
            return (
              <button
                key={code}
                type="button"
                role="option"
                aria-selected={active}
                className={`language-modal__row ${active ? "language-modal__row--current" : ""}`.trim()}
                onClick={() => pick(code as Locale)}
              >
                <span className="language-modal__flag" aria-hidden>
                  {row.flag}
                </span>
                <span className="language-modal__name">{row.label}</span>
                {active ? <span className="language-modal__badge">{t("languageModal.current")}</span> : null}
              </button>
            );
          })}
        </div>
      </div>
    </div>,
    document.body,
  );
}
