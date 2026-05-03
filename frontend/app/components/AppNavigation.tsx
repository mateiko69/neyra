"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import {
  ApiRateLimitError,
  ApiThrottleSkipError,
  AUTH_UNAUTHORIZED_EVENT,
  apiFetch,
  clearAuth,
  getToken,
  isAuthSessionTerminated,
} from "../../lib/api";
import { fetchDiscoverFeed } from "../../lib/discoverFeed";
import { CHAT_SYNC_EVENT, type ChatSyncDetail } from "../../lib/chat/api";
import { startChatRealtime, stopChatRealtime } from "../../lib/chat/realtime";
import { debugChat } from "../../lib/chat/debug";
import {
  ADMIN_NAV,
  AUTH_NAV,
  PRIMARY_NAV,
  NavBadgesResponse,
  formatBadgeCount,
  getPrimaryNavBadge,
  isAdminNavActive,
  isPrimaryNavActive,
  logoHref,
} from "../../lib/nav-config";
import {
  clearNavBadgesStore,
  getNavBadgesSnapshot,
  setNavBadgesFromServer,
  subscribeNavBadges,
} from "../../lib/navBadgesStore";
import { getI18nDebugClassName, inspectI18nText, joinClassNames, renderDebugText } from "./i18n/debugText";
import { NavIcon } from "./icons/NavIcons";
import { useT } from "./i18n/I18nProvider";
import { LanguageSwitcher } from "./i18n/LanguageSwitcher";
import { primeGrowthUserTier } from "../../lib/analytics/growthContext";
import { resolvePlanTier } from "../../lib/monetization/tiers";

type Me = { user_id: number; email: string; display_name: string; is_admin?: boolean };

/** Background badge poll cadence (only one timer). */
const BADGE_POLL_INTERVAL_MS = 20_000;
/** Minimum time between /nav/badges network attempts (stale-time / anti-burst). */
const BADGE_FETCH_COOLDOWN_MS = 15_000;
/** Merge bursty chat events into one badge refresh trigger. */
const CHAT_BADGE_TRIGGER_COALESCE_MS = 3_000;
/** Let chat events settle briefly before asking nav badges to reconcile. */
const CHAT_BADGE_REFRESH_DEBOUNCE_MS = 1_000;

export function AppNavigation() {
  const pathname = usePathname() || "/";
  const router = useRouter();
  const { t } = useT("AppNavigation");
  const [authed, setAuthed] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [tier, setTier] = useState<"free" | "premium" | "premium_plus">("free");

  useEffect(() => {
    primeGrowthUserTier(tier);
  }, [tier]);
  const badges = useSyncExternalStore(subscribeNavBadges, getNavBadgesSnapshot, getNavBadgesSnapshot);
  const meHydrateAttemptedRef = useRef(false);
  /** At most one /nav/badges request in flight. */
  const badgesInFlightRef = useRef(false);
  /** Single poll timer; always cleared before creating another. */
  const badgePollIntervalRef = useRef<number | null>(null);
  /** Last time a badge fetch attempt finished (success or handled error); enforces cooldown. */
  const lastBadgesFetchAtRef = useRef(0);
  /** Preserve one follow-up refresh if an important event lands mid-request. */
  const queuedBadgeRefreshRef = useRef<{ reason: string; force?: boolean; bypassCooldown?: boolean; skipCache?: boolean } | null>(null);
  /** Used to refresh once when leaving a chat route. */
  const previousPathnameRef = useRef(pathname);
  /** Debounce bursty chat sync badge refreshes. */
  const chatSyncBadgeDebounceRef = useRef<number | null>(null);
  /** If a chat-triggered refresh is already scheduled, do not schedule another. */
  const chatSyncBadgePendingRef = useRef(false);
  /** Strict coalescing window for chat-driven badge refreshes. */
  const lastChatBadgeTriggerAtRef = useRef(0);

  /** Full sync (token + /auth/me). Call once on mount only. */
  const refreshAuth = useCallback(() => {
    const token = getToken();
    setAuthed(Boolean(token));
    if (!token) {
      meHydrateAttemptedRef.current = false;
      setMe(null);
      setTier("free");
      clearNavBadgesStore("nav-refresh-auth-no-token");
      return;
    }
    meHydrateAttemptedRef.current = true;
    apiFetch("/auth/me")
      .then((r) => setMe(r as Me))
      .catch(() => {
        setMe(null);
        setAuthed(Boolean(getToken()));
      });
    apiFetch("/subscriptions/me", { metaReason: "nav-subscription", skipThrottle: true })
      .then((r) => setTier(resolvePlanTier(r as any)))
      .catch(() => setTier("free"));
  }, []);

  const cancelPendingChatBadgeRefresh = useCallback(() => {
    if (chatSyncBadgeDebounceRef.current != null) {
      window.clearTimeout(chatSyncBadgeDebounceRef.current);
      chatSyncBadgeDebounceRef.current = null;
    }
    chatSyncBadgePendingRef.current = false;
  }, []);

  const stopAllBadgePolling = useCallback(() => {
    if (badgePollIntervalRef.current != null) {
      clearInterval(badgePollIntervalRef.current);
      badgePollIntervalRef.current = null;
    }
    cancelPendingChatBadgeRefresh();
    lastBadgesFetchAtRef.current = 0;
    queuedBadgeRefreshRef.current = null;
    lastChatBadgeTriggerAtRef.current = 0;
  }, [cancelPendingChatBadgeRefresh]);

  useEffect(() => {
    const onUnauthorized = () => stopAllBadgePolling();
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
  }, [stopAllBadgePolling]);

  useEffect(() => {
    if (!authed || !getToken()) return;
    if (pathname === "/") return;
    // Prefetch likely next screens so navigation feels instant.
    try {
      void router.prefetch("/discover");
      void router.prefetch("/chat");
      void router.prefetch("/likes");
      void router.prefetch("/profile");
      void router.prefetch("/subscription");
      // Warm GET /discover/feed cache so first open paints faster (shares apiFetch cache + single-flight).
      void fetchDiscoverFeed("nav-prefetch-discover", { skipCache: false }).promise.catch(() => {});
    } catch {
      // ignore
    }
  }, [authed, router, pathname]);

  const refreshBadges = useCallback(async (
    reason: string,
    opts?: { force?: boolean; bypassCooldown?: boolean; skipCache?: boolean },
  ) => {
    if (isAuthSessionTerminated()) {
      return;
    }
    if (!getToken()) {
      clearNavBadgesStore("nav-refresh-badges-no-token");
      return;
    }
    const now = Date.now();
    if (
      !opts?.bypassCooldown &&
      lastBadgesFetchAtRef.current > 0 &&
      now - lastBadgesFetchAtRef.current < BADGE_FETCH_COOLDOWN_MS
    ) {
      return;
    }
    if (badgesInFlightRef.current) {
      queuedBadgeRefreshRef.current = {
        reason,
        force: queuedBadgeRefreshRef.current?.force || opts?.force,
        bypassCooldown: queuedBadgeRefreshRef.current?.bypassCooldown || opts?.bypassCooldown,
        skipCache: queuedBadgeRefreshRef.current?.skipCache || opts?.skipCache,
      };
      return;
    }
    badgesInFlightRef.current = true;
    try {
      const r = await apiFetch("/nav/badges", {
        metaReason: reason,
        // Never bypass throttle for /nav/badges; chat events can be bursty across routes.
        skipCache: opts?.skipCache === true,
        softFail: true,
      });
      if (r === undefined) return;
      setNavBadgesFromServer(r as NavBadgesResponse, reason);
      lastBadgesFetchAtRef.current = Date.now();
    } catch (e: unknown) {
      if (e instanceof ApiThrottleSkipError) return;
      if (e instanceof ApiRateLimitError) {
        lastBadgesFetchAtRef.current = Date.now();
        return;
      }
      lastBadgesFetchAtRef.current = Date.now();
      debugChat("nav badges refresh failed", { reason, error: e, badges: getNavBadgesSnapshot() });
    } finally {
      badgesInFlightRef.current = false;
      if (queuedBadgeRefreshRef.current) {
        const next = queuedBadgeRefreshRef.current;
        queuedBadgeRefreshRef.current = null;
        void refreshBadges(next.reason, next);
      }
    }
  }, []);

  const scheduleChatBadgeRefresh = useCallback((reason: string) => {
    if (!getToken()) return;
    if (badgesInFlightRef.current) {
      debugChat("skip chat-triggered nav badge refresh while request is already in flight", { reason });
      return;
    }
    if (chatSyncBadgePendingRef.current) {
      debugChat("skip duplicate scheduled chat-triggered nav badge refresh", { reason });
      return;
    }
    const now = Date.now();
    const sinceLastTrigger = now - lastChatBadgeTriggerAtRef.current;
    if (
      lastChatBadgeTriggerAtRef.current > 0 &&
      sinceLastTrigger < CHAT_BADGE_TRIGGER_COALESCE_MS
    ) {
      debugChat("coalesced chat-triggered nav badge refresh", {
        reason,
        sinceLastTriggerMs: sinceLastTrigger,
      });
      return;
    }

    chatSyncBadgePendingRef.current = true;
    lastChatBadgeTriggerAtRef.current = now;
    chatSyncBadgeDebounceRef.current = window.setTimeout(() => {
      chatSyncBadgeDebounceRef.current = null;
      chatSyncBadgePendingRef.current = false;
      void refreshBadges("nav-badges-chat-sync", {
        bypassCooldown: true,
        // For thread-open + message-received, force a fresh reconcile so badges update immediately.
        // For other chat sync events, allow short GET cache to prevent bursts.
        skipCache: reason.includes("threadOpened") || reason.includes("messageReceived"),
      });
    }, CHAT_BADGE_REFRESH_DEBOUNCE_MS);
  }, [refreshBadges]);

  useEffect(() => {
    refreshAuth();
  }, [refreshAuth]);

  // Realtime: connect to chat websocket when authed & me is known.
  useEffect(() => {
    const shouldRun = pathname.startsWith("/chat");
    if (!shouldRun || !authed || !getToken() || !me?.user_id) {
      stopChatRealtime();
      return;
    }
    startChatRealtime(me.user_id);
    return () => stopChatRealtime();
  }, [authed, me?.user_id, pathname]);

  /** Route changes: sync auth flag from storage only (no /auth/me per navigation). */
  useEffect(() => {
    const token = getToken();
    setAuthed(Boolean(token));
    if (!token) {
      meHydrateAttemptedRef.current = false;
      setMe(null);
      cancelPendingChatBadgeRefresh();
      lastChatBadgeTriggerAtRef.current = 0;
      clearNavBadgesStore("nav-route-no-token");
    }
  }, [pathname, cancelPendingChatBadgeRefresh]);

  /**
   * Client-side login: mount already ran refreshAuth; this only runs when `authed` becomes true
   * with a cold `me`. Intentionally omit `me` from deps to avoid re-running when /auth/me returns.
   */
  useEffect(() => {
    if (!authed || !getToken()) return;
    if (meHydrateAttemptedRef.current) return;
    meHydrateAttemptedRef.current = true;
    apiFetch("/auth/me")
      .then((r) => setMe(r as Me))
      .catch(() => {
        setMe(null);
        meHydrateAttemptedRef.current = false;
        setAuthed(Boolean(getToken()));
      });
  }, [authed]);

  /**
   * Badges: one fetch when authed (bypass cooldown), then interval only — deps exclude `pathname`
   * so route rerenders never touch /nav/badges; `refreshBadges` is stable (empty useCallback deps).
   */
  useEffect(() => {
    const clearBadgeInterval = () => {
      if (badgePollIntervalRef.current != null) {
        clearInterval(badgePollIntervalRef.current);
        badgePollIntervalRef.current = null;
      }
    };

    if (!authed || !getToken()) {
      lastBadgesFetchAtRef.current = 0;
      queuedBadgeRefreshRef.current = null;
      cancelPendingChatBadgeRefresh();
      lastChatBadgeTriggerAtRef.current = 0;
      clearBadgeInterval();
      return;
    }

    if (pathname === "/") {
      lastBadgesFetchAtRef.current = 0;
      queuedBadgeRefreshRef.current = null;
      cancelPendingChatBadgeRefresh();
      lastChatBadgeTriggerAtRef.current = 0;
      clearBadgeInterval();
      return;
    }

    if (badgePollIntervalRef.current != null) {
      clearInterval(badgePollIntervalRef.current);
      badgePollIntervalRef.current = null;
    }

    void refreshBadges("nav-badges-initial", { force: false, bypassCooldown: true });

    badgePollIntervalRef.current = window.setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState !== "visible") return;
      if (isAuthSessionTerminated()) return;
      if (!getToken()) return;
      void refreshBadges("nav-badges-interval", { force: false });
    }, BADGE_POLL_INTERVAL_MS);

    return () => {
      clearBadgeInterval();
    };
  }, [authed, refreshBadges, cancelPendingChatBadgeRefresh, pathname]);

  /** When returning to the tab, reconcile badges once (cache + cooldown still apply inside refreshBadges). */
  useEffect(() => {
    if (!authed || !getToken()) return;
    if (pathname === "/") return;
    const onVis = () => {
      if (typeof document !== "undefined" && document.visibilityState !== "visible") return;
      if (isAuthSessionTerminated()) return;
      void refreshBadges("nav-badges-visibility", { bypassCooldown: true });
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [authed, refreshBadges, pathname]);

  useEffect(() => {
    if (!authed || !getToken()) {
      previousPathnameRef.current = pathname;
      return;
    }
    const previous = previousPathnameRef.current;
    previousPathnameRef.current = pathname;
    if (previous === pathname) return;
    if (previous.startsWith("/chat") && !pathname.startsWith("/chat")) {
      cancelPendingChatBadgeRefresh();
      lastChatBadgeTriggerAtRef.current = 0;
      void refreshBadges("nav-badges-leave-chat", {
        bypassCooldown: true,
        skipCache: false,
      });
    }
  }, [authed, pathname, refreshBadges, cancelPendingChatBadgeRefresh]);

  useEffect(() => {
    if (!authed || !getToken()) return;
    const onChatSync = (event: Event) => {
      const detail = (event as CustomEvent<ChatSyncDetail>).detail;
      debugChat("nav chat sync received", detail);
      if (!detail) return;
      scheduleChatBadgeRefresh(`chat-sync:${detail.type}`);
    };
    window.addEventListener(CHAT_SYNC_EVENT, onChatSync);
    return () => {
      cancelPendingChatBadgeRefresh();
      window.removeEventListener(CHAT_SYNC_EVENT, onChatSync);
    };
  }, [authed, scheduleChatBadgeRefresh, cancelPendingChatBadgeRefresh]);

  function logout() {
    clearAuth();
    meHydrateAttemptedRef.current = false;
    stopAllBadgePolling();
    setAuthed(false);
    setMe(null);
    router.replace(AUTH_NAV.login.href);
  }

  const adminActive = isAdminNavActive(pathname);
  const brandHomeAria = inspectI18nText(t("brand.homeAria"), { component: "AppNavigation", prop: "brand.homeAria" });
  const navMainLabel = inspectI18nText(t("nav.main"), { component: "AppNavigation", prop: "nav.main" });
  const mobileMainLabel = inspectI18nText(t("nav.mobileMain"), { component: "AppNavigation", prop: "nav.mobileMain" });

  function primaryNavLabel(item: (typeof PRIMARY_NAV)[number]) {
    return t(item.labelKey);
  }

  return (
    <>
      <header className="shell-top" role="banner">
        <div className="shell-top-inner">
          <div className="shell-brand-slot">
            <Link href={logoHref(authed)} className="brand brand-link" aria-label={brandHomeAria.text}>
              <div className="brand-mark" aria-hidden />
              <div className="brand-text">
                <div className="brand-title">{renderDebugText(t("brand.name"), { component: "AppNavigation", prop: "brand.name" })}</div>
                <div className="brand-sub">{renderDebugText(t("brand.subtitle"), { component: "AppNavigation", prop: "brand.subtitle" })}</div>
              </div>
            </Link>
          </div>

          {authed ? (
            <nav className="shell-nav-center" aria-label={navMainLabel.text}>
              {PRIMARY_NAV.map((item) => {
                const active = isPrimaryNavActive(pathname, item);
                const badge = getPrimaryNavBadge(item, badges);
                const label = primaryNavLabel(item);
                return (
                  <Link
                    key={item.id}
                    data-testid={`nav-${item.id}`}
                    href={item.href}
                    className={`nav-pill ${active ? "nav-pill-active" : ""}`}
                    aria-current={active ? "page" : undefined}
                  >
                    <span className="nav-pill-icon" aria-hidden>
                      <NavIcon id={item.icon} />
                    </span>
                    <span className="nav-pill-label">
                      {renderDebugText(label, { component: "AppNavigation", prop: `desktop-nav.${item.id}` })}
                    </span>
                    {badge ? (
                      <span
                        className={
                          badge.tone === "amber" ? "nav-count-badge nav-count-badge--amber" : "nav-count-badge"
                        }
                        title={
                          inspectI18nText(
                            badge.tone === "amber"
                              ? t("nav.badge.new", { count: badge.count })
                              : t("nav.badge.unread", { count: badge.count }),
                            { component: "AppNavigation", prop: `desktop-badge.${item.id}` },
                          ).text
                        }
                      >
                        {formatBadgeCount(badge.count)}
                      </span>
                    ) : null}
                  </Link>
                );
              })}
            </nav>
          ) : (
            <div className="shell-nav-spacer" aria-hidden />
          )}

          <div className="shell-actions">
            {authed ? (
              <>
                {tier !== "free" ? (
                  <Link href="/subscription?source=nav_premium_badge" className="nav-pill nav-pill-ghost nav-pill-quiet" style={{ fontWeight: 850 }}>
                    ⭐ {t("premium.badge")}
                  </Link>
                ) : null}
                <LanguageSwitcher />
                {me?.is_admin ? (
                  <Link
                    href={ADMIN_NAV.href}
                    className={`nav-pill nav-pill-ghost ${adminActive ? "nav-pill-active" : ""}`}
                    aria-current={adminActive ? "page" : undefined}
                  >
                    {renderDebugText(t("nav.admin"), { component: "AppNavigation", prop: "nav.admin" })}
                  </Link>
                ) : null}
                <button type="button" className="nav-pill nav-pill-ghost nav-pill-quiet" onClick={logout}>
                  {renderDebugText(t("nav.logout"), { component: "AppNavigation", prop: "nav.logout" })}
                </button>
              </>
            ) : (
              <>
                <LanguageSwitcher compact />
                <Link
                  href={AUTH_NAV.login.href}
                  className={`nav-pill ${AUTH_NAV.login.variant === "ghost" ? "nav-pill-ghost" : ""} ${pathname.startsWith(AUTH_NAV.login.href) ? "nav-pill-active" : ""}`}
                >
                  {renderDebugText(t("nav.login"), { component: "AppNavigation", prop: "nav.login" })}
                </Link>
                <Link
                  href={AUTH_NAV.signup.href}
                  className={`nav-pill ${AUTH_NAV.signup.variant === "ghost" ? "nav-pill-ghost" : ""} ${pathname.startsWith(AUTH_NAV.signup.href) ? "nav-pill-active" : ""}`}
                >
                  {renderDebugText(t("nav.signup"), { component: "AppNavigation", prop: "nav.signup" })}
                </Link>
              </>
            )}
          </div>
        </div>
      </header>

      {authed ? (
        <nav className="shell-bottom" role="navigation" aria-label={mobileMainLabel.text}>
          <div className="shell-bottom-inner">
            {PRIMARY_NAV.map((item) => {
              const active = isPrimaryNavActive(pathname, item);
              const badge = getPrimaryNavBadge(item, badges);
              const label = primaryNavLabel(item);
              return (
                <Link
                  key={item.id}
                  data-testid={`nav-${item.id}`}
                  href={item.href}
                  className={`bottom-pill ${active ? "bottom-pill-active" : ""}`}
                  aria-current={active ? "page" : undefined}
                >
                  <span className="bottom-pill-icon-wrap">
                    <NavIcon id={item.icon} className="bottom-pill-icon" />
                    {badge ? (
                      <span
                        className={
                          badge.tone === "amber"
                            ? "bottom-count-badge bottom-count-badge--amber"
                            : "bottom-count-badge"
                        }
                        title={
                          inspectI18nText(
                            badge.tone === "amber"
                              ? t("nav.badge.new", { count: badge.count })
                              : t("nav.badge.unread", { count: badge.count }),
                            { component: "AppNavigation", prop: `mobile-badge.${item.id}` },
                          ).text
                        }
                      >
                        {formatBadgeCount(badge.count)}
                      </span>
                    ) : null}
                  </span>
                  <span className="bottom-pill-label">
                    {renderDebugText(label, { component: "AppNavigation", prop: `mobile-nav.${item.id}` })}
                  </span>
                </Link>
              );
            })}
          </div>
        </nav>
      ) : null}
    </>
  );
}
