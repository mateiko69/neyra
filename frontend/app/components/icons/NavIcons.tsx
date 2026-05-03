import type { NavIconId } from "../../../lib/nav-config";

const common = {
  width: 22,
  height: 22,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function NavIcon({ id, className }: { id: NavIconId; className?: string }) {
  switch (id) {
    case "discover":
      return (
        <svg {...common} className={className} aria-hidden>
          <path d="M12 21a8 8 0 1 0-8-8c0 3.5 2.5 6.5 8 11 5.5-4.5 8-7.5 8-11a8 8 0 1 0-8 8Z" />
          <circle cx="12" cy="13" r="2.5" />
        </svg>
      );
    case "matches":
      return (
        <svg {...common} className={className} aria-hidden>
          <path d="M12 21s-6-4.35-6-9.5a3.5 3.5 0 0 1 6-2.36 3.5 3.5 0 0 1 6 2.36C18 16.65 12 21 12 21Z" />
        </svg>
      );
    case "chat":
      return (
        <svg {...common} className={className} aria-hidden>
          <path d="M8 10h.01M12 10h.01M16 10h.01M6 18l2-2h9a3 3 0 0 0 3-3V7a3 3 0 0 0-3-3H7a3 3 0 0 0-3 3v11Z" />
        </svg>
      );
    case "profile":
      return (
        <svg {...common} className={className} aria-hidden>
          <path d="M20 21a8 8 0 1 0-16 0" />
          <circle cx="12" cy="8" r="3.5" />
        </svg>
      );
    case "premium":
      return (
        <svg {...common} className={className} aria-hidden>
          <path d="M12 3 7 9l5 3 5-3-5-6Z" />
          <path d="M7 9v10a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V9" />
        </svg>
      );
    default:
      return null;
  }
}
