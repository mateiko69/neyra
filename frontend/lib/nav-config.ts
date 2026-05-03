/**
 * Single source of truth for NEYRA app navigation.
 * — Primary rail: max 5 items (Discover → Premium), authed only.
 * — Admin + auth links are separate; visibility handled in AppNavigation.
 */

export type NavIconId = "discover" | "matches" | "chat" | "profile" | "premium";

/** Response shape from GET /api/v1/nav/badges */
export type NavBadgesResponse = {
  unread_messages: number;
  chat_threads_unread: number;
  new_matches: number;
  /** Incoming likes waiting (Likes tab / people who liked you). */
  incoming_likes: number;
  /** Total mutual matches for the user. */
  matches: number;
  /** Matches tab attention: unseen new matches + pending incoming likes. */
  matches_attention: number;
};

/** Badge fields exposed on primary items (subset of API). */
export type PrimaryNavBadgeField = keyof Pick<NavBadgesResponse, "unread_messages" | "matches_attention">;

export type NavBadgeTone = "default" | "amber";

export type PrimaryNavItem = {
  /** Stable React key; unique. */
  id: string;
  href: string;
  /** i18n key for visible label (locales/en.json). */
  labelKey: string;
  icon: NavIconId;
  /** Path prefixes that count as “this section” (exact or nested). */
  activePrefixes: string[];
  /** Optional: show count from /nav/badges when greater than zero */
  badgeField?: PrimaryNavBadgeField;
  badgeTone?: NavBadgeTone;
};

/**
 * Main app sections — desktop center nav + mobile bottom bar (same 5, same order).
 * Do not duplicate these hrefs elsewhere; import this list only.
 */
export const PRIMARY_NAV: PrimaryNavItem[] = [
  {
    id: "discover",
    href: "/discover",
    labelKey: "navigation.discover",
    icon: "discover",
    activePrefixes: ["/discover"],
  },
  {
    id: "matches",
    href: "/matches",
    labelKey: "navigation.matches",
    icon: "matches",
    activePrefixes: ["/matches"],
    badgeField: "matches_attention",
    badgeTone: "amber",
  },
  {
    id: "chat",
    href: "/chat",
    labelKey: "navigation.chat",
    icon: "chat",
    activePrefixes: ["/chat"],
    badgeField: "unread_messages",
    badgeTone: "default",
  },
  {
    id: "profile",
    href: "/profile",
    labelKey: "navigation.profile",
    icon: "profile",
    activePrefixes: ["/profile"],
  },
  {
    id: "premium",
    href: "/subscription",
    labelKey: "navigation.premium",
    icon: "premium",
    activePrefixes: ["/subscription"],
  },
];

export type AdminNavItem = {
  id: string;
  href: string;
  label: string;
  activePrefixes: string[];
};

export const ADMIN_NAV: AdminNavItem = {
  id: "admin",
  href: "/admin",
  label: "Admin",
  activePrefixes: ["/admin"],
};

export type AuthNavLink = {
  id: string;
  href: string;
  label: string;
  variant: "ghost" | "emphasis";
};

export const AUTH_NAV: { login: AuthNavLink; signup: AuthNavLink } = {
  login: { id: "login", href: "/login", label: "Log in", variant: "ghost" },
  signup: { id: "signup", href: "/signup", label: "Sign up", variant: "emphasis" },
};

export function logoHref(authed: boolean): string {
  return authed ? "/discover" : "/";
}

export function isNavActive(pathname: string, activePrefixes: string[]): boolean {
  const p = pathname || "/";
  return activePrefixes.some((prefix) => p === prefix || p.startsWith(`${prefix}/`));
}

export function isPrimaryNavActive(pathname: string, item: PrimaryNavItem): boolean {
  return isNavActive(pathname, item.activePrefixes);
}

export function isAdminNavActive(pathname: string): boolean {
  return isNavActive(pathname, ADMIN_NAV.activePrefixes);
}

/** Badge pill for a primary item, or null if none. */
export function getPrimaryNavBadge(
  item: PrimaryNavItem,
  badges: NavBadgesResponse | null,
): { count: number; tone: NavBadgeTone } | null {
  if (!item.badgeField || !badges) return null;
  const raw = badges[item.badgeField];
  const count = typeof raw === "number" && raw > 0 ? Math.floor(raw) : 0;
  if (!count) return null;
  return { count, tone: item.badgeTone ?? "default" };
}

export function formatBadgeCount(count: number): string {
  return count > 9 ? "9+" : String(count);
}
