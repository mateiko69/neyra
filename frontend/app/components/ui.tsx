"use client";

import { ReactNode, useEffect, useMemo } from "react";
import { usePathname } from "next/navigation";
import { useT } from "./i18n/I18nProvider";
import { resolveToastPlacement, type ToastPlacement } from "../../lib/toastPlacement";
import {
  getI18nDebugClassName,
  inspectI18nText,
  joinClassNames,
  mergeI18nDebugStatus,
  renderDebugText,
} from "./i18n/debugText";

export function Card({
  children,
  className = "",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { children: ReactNode; className?: string }) {
  return (
    <div className={`card ${className}`} {...props}>
      {children}
    </div>
  );
}

export function Button({
  children,
  variant = "primary",
  className = "",
  title,
  "aria-label": ariaLabel,
  onClick,
  type,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost"; className?: string }) {
  const cls = variant === "primary" ? "btn btn-primary" : variant === "secondary" ? "btn btn-secondary" : "btn btn-ghost";
  const titleInfo = typeof title === "string" ? inspectI18nText(title, { component: "Button", prop: "title" }) : null;
  const ariaLabelInfo = typeof ariaLabel === "string" ? inspectI18nText(ariaLabel, { component: "Button", prop: "aria-label" }) : null;
  const childInfo =
    typeof children === "string" ? inspectI18nText(children, { component: "Button", prop: "children" }) : null;
  const debugStatus = mergeI18nDebugStatus(titleInfo?.status, ariaLabelInfo?.status, childInfo?.status);

  const safeOnClick: typeof onClick =
    !onClick
      ? undefined
      : (event) => {
          try {
            const result = onClick(event) as unknown;
            if (typeof process !== "undefined" && process.env.NODE_ENV !== "production") {
              if (typeof (result as any)?.then === "function") {
                void (result as Promise<unknown>).catch((error: unknown) => {
                  // eslint-disable-next-line no-console
                  console.warn("[click-audit] button onClick rejected", { error });
                });
              }
            }
            return result;
          } catch (error) {
            if (typeof process !== "undefined" && process.env.NODE_ENV !== "production") {
              // eslint-disable-next-line no-console
              console.warn("[click-audit] button onClick threw", { error });
            }
            throw error;
          }
        };
  return (
    <button
      className={joinClassNames(cls, className, getI18nDebugClassName(debugStatus))}
      title={titleInfo?.text ?? title}
      aria-label={ariaLabelInfo?.text ?? ariaLabel}
      data-i18n-debug={debugStatus ?? undefined}
      type={type ?? "button"}
      onClick={safeOnClick}
      {...props}
    >
      {renderDebugText(children, { component: "Button", prop: "children" })}
    </button>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const {
    className,
    placeholder,
    title,
    "aria-label": ariaLabel,
    ...inputProps
  } = props;
  const placeholderInfo =
    typeof placeholder === "string"
      ? inspectI18nText(placeholder, { component: "Input", prop: "placeholder" })
      : null;
  const ariaLabelInfo =
    typeof ariaLabel === "string"
      ? inspectI18nText(ariaLabel, { component: "Input", prop: "aria-label" })
      : null;
  const titleInfo = typeof title === "string" ? inspectI18nText(title, { component: "Input", prop: "title" }) : null;
  const debugStatus = mergeI18nDebugStatus(placeholderInfo?.status, ariaLabelInfo?.status, titleInfo?.status);
  return (
    <input
      className={joinClassNames("input", className || "", getI18nDebugClassName(debugStatus, "field"))}
      placeholder={placeholderInfo?.text ?? placeholder}
      aria-label={ariaLabelInfo?.text ?? ariaLabel}
      title={titleInfo?.text ?? title}
      data-i18n-debug={debugStatus ?? undefined}
      {...inputProps}
    />
  );
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const {
    className,
    placeholder,
    title,
    "aria-label": ariaLabel,
    ...textareaProps
  } = props;
  const placeholderInfo =
    typeof placeholder === "string"
      ? inspectI18nText(placeholder, { component: "Textarea", prop: "placeholder" })
      : null;
  const ariaLabelInfo =
    typeof ariaLabel === "string"
      ? inspectI18nText(ariaLabel, { component: "Textarea", prop: "aria-label" })
      : null;
  const titleInfo = typeof title === "string" ? inspectI18nText(title, { component: "Textarea", prop: "title" }) : null;
  const debugStatus = mergeI18nDebugStatus(placeholderInfo?.status, ariaLabelInfo?.status, titleInfo?.status);
  return (
    <textarea
      className={joinClassNames("input", className || "", getI18nDebugClassName(debugStatus, "field"))}
      placeholder={placeholderInfo?.text ?? placeholder}
      aria-label={ariaLabelInfo?.text ?? ariaLabel}
      title={titleInfo?.text ?? title}
      data-i18n-debug={debugStatus ?? undefined}
      {...textareaProps}
    />
  );
}

export function Chip({ children }: { children: ReactNode }) {
  const childInfo =
    typeof children === "string" ? inspectI18nText(children, { component: "Chip", prop: "children", allowRaw: true }) : null;
  return (
    <span className={joinClassNames("chip", getI18nDebugClassName(childInfo?.status ?? null))} data-i18n-debug={childInfo?.status ?? undefined}>
      {renderDebugText(children, { component: "Chip", prop: "children", allowRaw: true })}
    </span>
  );
}

export function Badge({ children, tone = "default" }: { children: ReactNode; tone?: "default" | "premium" | "streak" }) {
  const cls = tone === "premium" ? "badge badge-premium" : tone === "streak" ? "badge badge-streak" : "badge";
  const childInfo =
    typeof children === "string" ? inspectI18nText(children, { component: "Badge", prop: "children", allowRaw: true }) : null;
  return (
    <span className={joinClassNames(cls, getI18nDebugClassName(childInfo?.status ?? null))} data-i18n-debug={childInfo?.status ?? undefined}>
      {renderDebugText(children, { component: "Badge", prop: "children", allowRaw: true })}
    </span>
  );
}

export function Skeleton({ style, className = "" }: { style?: React.CSSProperties; className?: string }) {
  return <div className={`skeleton ${className}`} style={style} />;
}

export function Toast({
  text,
  onClose,
  placement = "auto",
  autoDismissMs = 5200,
}: {
  text: string | null;
  onClose: () => void;
  placement?: ToastPlacement;
  autoDismissMs?: number;
}) {
  const { t } = useT("Toast");
  const pathname = usePathname() || "/";
  const pos = useMemo(() => resolveToastPlacement(pathname, placement), [placement, pathname]);
  useEffect(() => {
    if (!text || autoDismissMs <= 0) return;
    const timer = window.setTimeout(() => onClose(), autoDismissMs);
    return () => window.clearTimeout(timer);
  }, [text, autoDismissMs, onClose]);
  if (!text) return null;
  const toastInfo = inspectI18nText(text, { component: "Toast", prop: "text", allowRaw: true });
  return (
    <div
      className={joinClassNames("toast", `toast--${pos}`, getI18nDebugClassName(toastInfo.status))}
      role="status"
      aria-live="polite"
      data-i18n-debug={toastInfo.status ?? undefined}
    >
      <div className="body">{renderDebugText(text, { component: "Toast", prop: "text", allowRaw: true })}</div>
      <div className="caption toast__caption">
        {renderDebugText(t("common.tapToDismiss"), { component: "Toast", prop: "dismissHint" })}{" "}
        <button type="button" className="toast__dismiss" onClick={onClose} aria-label={t("common.dismiss")}>
          {t("common.dismiss")}
        </button>
      </div>
    </div>
  );
}
