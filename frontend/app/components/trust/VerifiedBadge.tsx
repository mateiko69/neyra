"use client";

import type { ReactNode } from "react";
import { useId } from "react";

type Props = {
  label?: ReactNode;
  className?: string;
  title?: string;
  size?: "sm" | "md";
};

export function VerifiedBadge({ label, className = "", title, size = "sm" }: Props) {
  const gid = useId().replace(/:/g, "");
  const dim = size === "md" ? 18 : 15;
  const gradId = `vb-${gid}`;
  return (
    <span className={`verified-badge-check trust-verified-pill--pulse ${className}`.trim()} title={title}>
      <svg width={dim} height={dim} viewBox="0 0 24 24" fill="none" aria-hidden className="verified-badge-check__svg">
        <circle cx="12" cy="12" r="11" fill={`url(#${gradId})`} opacity="0.95" />
        <path
          d="M7.2 12.4l2.8 2.8 6.8-6.8"
          stroke="white"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <defs>
          <linearGradient id={gradId} x1="4" y1="4" x2="20" y2="20">
            <stop stopColor="#3b82f6" />
            <stop offset="1" stopColor="#2563eb" />
          </linearGradient>
        </defs>
      </svg>
      {label ? <span className="verified-badge-check__label">{label}</span> : null}
    </span>
  );
}
