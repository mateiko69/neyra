import type { ReactNode } from "react";
import { getI18nDebugClassName, inspectI18nText, joinClassNames } from "./i18n/debugText";

type EmptyStateProps = {
  /** Short label above the title (e.g. emoji or 2-letter word) */
  kicker?: string;
  title: string;
  description: string;
  children?: ReactNode;
  /** Larger bottom padding inside the block */
  spacious?: boolean;
  allowRawKicker?: boolean;
  allowRawTitle?: boolean;
  allowRawDescription?: boolean;
};

/**
 * Premium empty / zero-state pattern — intentional copy and clear hierarchy.
 */
export function EmptyState({
  kicker,
  title,
  description,
  children,
  spacious,
  allowRawKicker = false,
  allowRawTitle = false,
  allowRawDescription = false,
}: EmptyStateProps) {
  const kickerInfo = kicker
    ? inspectI18nText(kicker, { component: "EmptyState", prop: "kicker", allowRaw: allowRawKicker })
    : null;
  const titleInfo = inspectI18nText(title, { component: "EmptyState", prop: "title", allowRaw: allowRawTitle });
  const descriptionInfo = inspectI18nText(description, {
    component: "EmptyState",
    prop: "description",
    allowRaw: allowRawDescription,
  });
  return (
    <div className={`empty-state${spacious ? " empty-state--spacious" : ""}`}>
      {kickerInfo ? (
        <div
          className={joinClassNames("empty-state-kicker", getI18nDebugClassName(kickerInfo.status))}
          data-i18n-debug={kickerInfo.status ?? undefined}
        >
          {kickerInfo.text}
        </div>
      ) : null}
      <h2
        className={joinClassNames("empty-state-title", getI18nDebugClassName(titleInfo.status))}
        data-i18n-debug={titleInfo.status ?? undefined}
      >
        {titleInfo.text}
      </h2>
      <p
        className={joinClassNames("empty-state-desc", getI18nDebugClassName(descriptionInfo.status))}
        data-i18n-debug={descriptionInfo.status ?? undefined}
      >
        {descriptionInfo.text}
      </p>
      {children ? <div className="empty-state-actions">{children}</div> : null}
    </div>
  );
}
