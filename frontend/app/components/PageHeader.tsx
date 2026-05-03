import type { ReactNode } from "react";
import { getI18nDebugClassName, inspectI18nText, joinClassNames } from "./i18n/debugText";

type PageHeaderProps = {
  title: string;
  subtitle?: string;
  /** Muted status line under subtitle (e.g. plan, sync state). */
  status?: string;
  /** `live` shows a pulse dot; `neutral` is text only (e.g. read-only screens). */
  statusVariant?: "live" | "neutral";
  /** Small label / badge cluster (e.g. Live, Premium) — shown beside actions. */
  badge?: ReactNode;
  /** Primary actions (buttons, links). */
  action?: ReactNode;
  variant?: "hero" | "section";
  allowRawTitle?: boolean;
  allowRawSubtitle?: boolean;
  allowRawStatus?: boolean;
};

export function PageHeader({
  title,
  subtitle,
  status,
  statusVariant = "live",
  badge,
  action,
  variant = "hero",
  allowRawTitle = false,
  allowRawSubtitle = false,
  allowRawStatus = false,
}: PageHeaderProps) {
  const titleSize = variant === "hero" ? 36 : 24;
  const hasMeta = Boolean(badge || action);
  const titleInfo = inspectI18nText(title, { component: "PageHeader", prop: "title", allowRaw: allowRawTitle });
  const subtitleInfo = subtitle
    ? inspectI18nText(subtitle, { component: "PageHeader", prop: "subtitle", allowRaw: allowRawSubtitle })
    : null;
  const statusInfo = status
    ? inspectI18nText(status, { component: "PageHeader", prop: "status", allowRaw: allowRawStatus })
    : null;

  return (
    <header className={`page-header page-header--${variant}`}>
      <div className="page-header-row">
        <div className="page-header-text">
          <h1
            className={joinClassNames("page-header-title", getI18nDebugClassName(titleInfo.status))}
            style={{ fontSize: titleSize }}
            data-i18n-debug={titleInfo.status ?? undefined}
          >
            {titleInfo.text}
          </h1>
          {subtitleInfo ? (
            <p
              className={joinClassNames("page-header-subtitle", getI18nDebugClassName(subtitleInfo.status))}
              data-i18n-debug={subtitleInfo.status ?? undefined}
            >
              {subtitleInfo.text}
            </p>
          ) : null}
          {status ? (
            <p
              className={joinClassNames("page-header-status", getI18nDebugClassName(statusInfo?.status ?? null))}
              data-i18n-debug={statusInfo?.status ?? undefined}
            >
              {statusVariant === "live" ? <span className="page-header-status-dot" aria-hidden /> : null}
              {statusInfo?.text ?? status}
            </p>
          ) : null}
        </div>
        {hasMeta ? (
          <div className="page-header-meta">
            {badge ? <div className="page-header-badge">{badge}</div> : null}
            {action ? <div className="page-header-action">{action}</div> : null}
          </div>
        ) : null}
      </div>
    </header>
  );
}
