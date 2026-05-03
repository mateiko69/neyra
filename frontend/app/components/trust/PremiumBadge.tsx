"use client";

type Props = { className?: string; title?: string };

export function PremiumBadge({ className = "", title }: Props) {
  return (
    <span className={`premium-badge-gold ${className}`.trim()} title={title}>
      <span className="premium-badge-gold__glow" aria-hidden />
      <span className="premium-badge-gold__text">✦</span>
    </span>
  );
}
