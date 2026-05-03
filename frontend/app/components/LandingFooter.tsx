"use client";

import Link from "next/link";
import { useT } from "./i18n/I18nProvider";

export function LandingFooter() {
  const { t } = useT("LandingPage");
  return (
    <footer
      className="surface"
      style={{
        marginTop: 8,
        padding: "24px 20px 28px",
        borderRadius: "var(--r-lg)",
        border: "1px solid rgba(255,255,255,0.1)",
        maxWidth: 980,
        marginLeft: "auto",
        marginRight: "auto",
        width: "100%",
      }}
    >
      <p className="body muted" style={{ margin: "0 0 16px", lineHeight: 1.55, maxWidth: "52ch" }}>
        {t("landing.footer.tagline")}
      </p>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "12px 20px",
          fontSize: 14,
          fontWeight: 750,
        }}
      >
        <Link className="body" style={{ color: "var(--accent)" }} href="/privacy">
          {t("landing.footer.privacy")}
        </Link>
        <Link className="body" style={{ color: "var(--accent)" }} href="/terms">
          {t("landing.footer.terms")}
        </Link>
        <Link className="body" style={{ color: "var(--accent)" }} href="/refund">
          {t("landing.footer.refund")}
        </Link>
        <Link className="body" style={{ color: "var(--accent)" }} href="/contact">
          {t("landing.footer.contact")}
        </Link>
      </div>
    </footer>
  );
}
