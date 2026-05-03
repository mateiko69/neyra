"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

function labelForElement(el: Element): string {
  const aria = el.getAttribute("aria-label");
  if (aria && aria.trim()) return aria.trim();
  const title = el.getAttribute("title");
  if (title && title.trim()) return title.trim();
  const text = (el as HTMLElement).innerText || (el as HTMLElement).textContent || "";
  return text.trim().replace(/\s+/g, " ").slice(0, 140);
}

function describeTarget(target: EventTarget | null): {
  tag: string;
  label: string;
  href: string | null;
  disabled: boolean;
  type: string | null;
} | null {
  if (!target || !(target instanceof Element)) return null;
  const el = target.closest("button, a, [role='button']") as Element | null;
  if (!el) return null;
  const tag = el.tagName.toLowerCase();
  const href = tag === "a" ? (el.getAttribute("href") || null) : null;
  const disabled =
    tag === "button"
      ? Boolean((el as HTMLButtonElement).disabled)
      : el.getAttribute("aria-disabled") === "true";
  const type = tag === "button" ? ((el as HTMLButtonElement).getAttribute("type") || null) : null;
  return { tag, label: labelForElement(el), href, disabled, type };
}

export function DevClickAudit() {
  const pathname = usePathname() || "/";

  useEffect(() => {
    if (typeof process === "undefined" || process.env.NODE_ENV === "production") return;

    const onClickCapture = (event: MouseEvent) => {
      const info = describeTarget(event.target);
      if (!info) return;
      // eslint-disable-next-line no-console
      console.log("[click-audit]", {
        path: pathname,
        ...info,
      });
    };

    document.addEventListener("click", onClickCapture, true);
    return () => document.removeEventListener("click", onClickCapture, true);
  }, [pathname]);

  return null;
}

