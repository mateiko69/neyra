"use client";

import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiThrottleSkipError, RateLimitError, apiFetch, getToken, invalidateApiGetCache } from "../../../lib/api";
import { fetchDiscoverFeed } from "../../../lib/discoverFeed";
import { photosFromList, resolveMediaUrl } from "../../../lib/media";
import { preloadDiscoverPhotoUrls } from "../../../lib/demoProfiles";
import { getAiOpeners, type AiOpenerMatchContext } from "../../../lib/chat/api";
import { discoverSwipeFeedback } from "../../../lib/discoverSwipeFeedback";
import { acquireDiscoverSwipe, releaseDiscoverSwipe, type DiscoverSwipeAction } from "../../../lib/discoverSwipeGuard";
import { PageShell } from "../../components/PageShell";
import { SafeImg } from "../../components/SafeImg";
import { Button, Toast } from "../../components/ui";
import { useT } from "../../components/i18n/I18nProvider";
import { DiscoverGuestPreview } from "../../components/discover/DiscoverGuestPreview";
import { setNavBadgesFromServer } from "../../../lib/navBadgesStore";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { localStorageDayShown, localStorageMarkDay, utcDayKey } from "../../../lib/retention/dedupe";
import { hasValueMoment, recordMatchMoment, recordOutboundLikeMoment } from "../../../lib/monetization/valueMoments";
import { DiscoverProfileCard, type DiscoverCardData } from "./DiscoverProfileCard";
import { resolveDemoProfilePhoto } from "../../../lib/resolvePhoto";

type DiscoverCard = {
  user_id: number;
  profile_id?: number | null;
  display_name?: string;
  age?: number | null;
  city?: string | null;
  bio?: string | null;
  photo_urls?: string[] | string | null;
  compatibility_score?: number | null;
  top_reasons?: string[] | null;
  vibe?: string | null;
  lifestyle_tags?: string[] | null;
  interests?: string[] | string | null;
  top_interests?: string[] | null;
  shared_interests?: string[] | null;
  badges?: { new?: boolean; active_now?: boolean; verified?: boolean } | null;
  smart_score?: number | null;
  boost_active?: boolean | null;
  /** True when Discover relaxed filters so the deck is non-empty (see API debug `fallback_used`). */
  discover_fallback_used?: boolean | null;
  discover_fallback_stage?: string | null;
  discover_profile_incomplete?: boolean | null;
  discover_missing_photo?: boolean | null;
  is_demo_profile?: boolean | null;
  demo_premium_showcase?: boolean | null;
  demo_personality_type?: string | null;
  gender?: string | null;
  distance_km?: number | null;
  last_active_at?: string | null;
  active_today?: boolean | null;
  ai_match?: boolean | null;
  visual_compatibility?: number | null;
  trusted?: string | null;
  is_verified?: boolean | null;
  verification_badge_visible?: boolean | null;
  is_premium?: boolean | null;
  premium_until?: string | null;
  variable_reward?: DiscoverCardData["variable_reward"];
  variable_reward_delay_ms?: number | null;
  they_liked_you?: boolean | null;
};

function mapDiscoverCardToProfileData(card: DiscoverCard, viewerDemoPremiumFromMe: boolean): DiscoverCardData {
  const demoPremiumShowcase = Boolean(card.demo_premium_showcase ?? (viewerDemoPremiumFromMe && card.is_demo_profile));
  return {
    user_id: card.user_id,
    profile_id: card.profile_id ?? null,
    display_name: card.display_name ?? undefined,
    age: card.age ?? null,
    city: card.city ?? undefined,
    distance_km: card.distance_km ?? null,
    last_active_at: card.last_active_at ?? null,
    active_today: card.active_today ?? null,
    bio: card.bio ?? undefined,
    photo_urls: card.photo_urls ?? undefined,
    verified: undefined,
    interests: Array.isArray(card.interests) ? card.interests : undefined,
    top_reasons: Array.isArray(card.top_reasons) ? card.top_reasons : undefined,
    compatibility_score: card.compatibility_score ?? null,
    ai_match: card.ai_match ?? undefined,
    visual_compatibility: card.visual_compatibility ?? null,
    trusted: (card.trusted as DiscoverCardData["trusted"]) ?? undefined,
    is_verified: card.is_verified ?? undefined,
    verification_badge_visible: card.verification_badge_visible ?? undefined,
    is_premium: card.is_premium ?? undefined,
    premium_until: card.premium_until ?? null,
    is_demo_profile: Boolean(card.is_demo_profile),
    demo_premium_showcase: demoPremiumShowcase,
    demo_personality_type: card.demo_personality_type ?? null,
    gender: card.gender ?? undefined,
    they_liked_you: card.they_liked_you ?? undefined,
    variable_reward: card.variable_reward ?? null,
    variable_reward_delay_ms: card.variable_reward_delay_ms ?? null,
  };
}

function clamp(n: number, a: number, b: number) {
  return Math.max(a, Math.min(b, n));
}

/** Dev-only diagnostics for Discover deck actions (no tokens). */
function devDiscoverDebug(payload: { action: DiscoverSwipeAction; profileId: number; deckLength: number }) {
  if (typeof process !== "undefined" && process.env.NODE_ENV === "development") {
    // eslint-disable-next-line no-console
    console.debug("[discover]", payload.action, { profileId: payload.profileId, deckLength: payload.deckLength });
  }
}

/*
 * Manual QA (mobile / narrow): Pass + Like always advance; rapid taps do not desync; Undo restores;
 * Boost opens paywall/toast only; no drag-swipe on coarse/narrow.
 */

/** Exit animation duration — must stay aligned with exit lock + button disable window (rapid-swipe queue). */
const DISCOVER_SWIPE_EXIT_MS = 520;
/** Deck advances ~after this from swipe start — shared by like/pass; never waits on `/swipes` (fixes stuck guard key on pass). */
const DISCOVER_SWIPE_ADVANCE_MS = DISCOVER_SWIPE_EXIT_MS + 120;
/** Like/Pass buttons (all viewports): short fade + nudge; 220–300ms range; must match advance timer. */
const DISCOVER_BUTTON_EXIT_MS = 280;
const DISCOVER_BUTTON_ADVANCE_MS = DISCOVER_BUTTON_EXIT_MS + 80;
/** If exit state never clears, force reset (mobile drag disabled — see comment on `discoverButtonOnly`). */
const DISCOVER_SWIPE_STUCK_RESET_MS = 600;

type DiscoverSwipeExitState = {
  liked: boolean;
  startX: number;
  startY: number;
  fly: boolean;
  /** True: Like/Pass button path — short nudge+fade (not 120vw fly). */
  simple?: boolean;
};

function toInterestsList(raw: unknown): string[] {
  if (Array.isArray(raw)) return raw.map((x) => String(x || "").trim()).filter(Boolean).slice(0, 6);
  if (typeof raw === "string") {
    return raw
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean)
      .slice(0, 6);
  }
  return [];
}

function isHeavySwipePassEmptyHint(debug: {
  filtered_by_pass: number;
  filtered_by_swipe: number;
  candidates_total: number;
}): boolean {
  const fp = Number(debug.filtered_by_pass) || 0;
  const fs = Number(debug.filtered_by_swipe) || 0;
  const t = Number(debug.candidates_total) || 0;
  if (t < 1) return false;
  if (fp >= 8 || fs >= 8) return true;
  if (t >= 8 && fp + fs >= Math.ceil(t * 0.45)) return true;
  return false;
}

function preloadImages(urls: string[]) {
  if (typeof window === "undefined") return;
  for (const src of urls) {
    if (!src) continue;
    try {
      const img = new Image();
      img.decoding = "async";
      img.loading = "eager";
      img.src = src;
    } catch {
      /* ignore */
    }
  }
}

function MatchModal({
  open,
  name,
  photoUrl,
  partnerUserId,
  matchContext,
  onSayHi,
  onStartWithDraft,
  onClose,
  t,
}: {
  open: boolean;
  name: string;
  photoUrl: string | null;
  partnerUserId: number | null;
  matchContext: AiOpenerMatchContext | null;
  onSayHi: () => void;
  onStartWithDraft: (draft: string) => void;
  onClose: () => void;
  t: (k: string, vars?: Record<string, string | number>) => string;
}) {
  const [loading, setLoading] = useState(false);
  const [openers, setOpeners] = useState<{ playful: string; confident: string; simple: string }>({
    playful: "",
    confident: "",
    simple: "",
  });

  useEffect(() => {
    if (!open || partnerUserId == null || partnerUserId <= 0) return;
    void trackAnalyticsEvent("match_moment_modal_shown", { partner_user_id: partnerUserId });
  }, [open, partnerUserId]);

  useEffect(() => {
    if (!open) return;
    // Mobile haptics (best-effort).
    try {
      if (typeof navigator !== "undefined" && typeof (navigator as any).vibrate === "function") {
        // Short celebratory pattern.
        (navigator as any).vibrate([20, 40, 20, 60, 30]);
      }
    } catch {
      /* ignore */
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if (!partnerUserId || !matchContext) return;
    let cancelled = false;
    setLoading(true);
    setOpeners({ playful: "", confident: "", simple: "" });
    void (async () => {
      try {
        const [playful, confident, simple] = await Promise.all([
          getAiOpeners(partnerUserId, matchContext, { style: "playful" }),
          getAiOpeners(partnerUserId, matchContext, { style: "confident" }),
          getAiOpeners(partnerUserId, matchContext, { style: "warm" }),
        ]);
        if (cancelled) return;
        setOpeners({
          playful: String(playful.items?.[0]?.text || playful.suggestions?.[0] || "").trim(),
          confident: String(confident.items?.[0]?.text || confident.suggestions?.[0] || "").trim(),
          simple: String(simple.items?.[0]?.text || simple.suggestions?.[0] || "").trim(),
        });
      } catch {
        if (cancelled) return;
        setOpeners({ playful: "", confident: "", simple: "" });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [matchContext, open, partnerUserId]);

  if (!open) return null;

  const suggestions = [
    {
      key: "playful",
      label: t("discover.match.start.playful"),
      text: openers.playful || t("discover.match.start.playful.fallback"),
    },
    {
      key: "confident",
      label: t("discover.match.start.confident"),
      text: openers.confident || t("discover.match.start.confident.fallback"),
    },
    {
      key: "simple",
      label: t("discover.match.start.simple"),
      text: openers.simple || t("discover.match.start.simple.fallback"),
    },
  ] as const;

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      className="ux-modal-backdrop"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.62)",
        display: "grid",
        placeItems: "center",
        zIndex: 50,
        padding: 18,
      }}
    >
      <div
        className="surface ux-modal-card"
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "100%",
          maxWidth: 420,
          borderRadius: 18,
          padding: 18,
          border: "1px solid rgba(255,255,255,0.14)",
          background: "rgba(20,18,24,0.96)",
        }}
      >
        <div className="h2" style={{ fontSize: 24, fontWeight: 900, letterSpacing: "-0.03em" }}>
          {t("discover.match.momentTitle")}
        </div>
        <div className="subtitle" style={{ marginTop: 8, opacity: 0.85 }}>
          {t("discover.match.momentSubtitle", { name })}
        </div>
        {photoUrl ? (
          <div style={{ marginTop: 14, width: "100%", aspectRatio: "1 / 1", borderRadius: 16, overflow: "hidden" }}>
            <SafeImg src={photoUrl} alt="" className="discover-card__img" loading="eager" />
          </div>
        ) : null}

        <div style={{ marginTop: 16, display: "grid", gap: 10 }}>
          <Button
            type="button"
            disabled={loading}
            onClick={() => {
              if (partnerUserId != null) {
                void trackAnalyticsEvent("ai_used", { source: "discover", surface: "match_modal_perfect_opener", partner_user_id: partnerUserId });
              }
              onStartWithDraft(suggestions[0].text);
            }}
          >
            {t("discover.match.ctaPerfectOpener")}
          </Button>
          <Button type="button" variant="secondary" onClick={onSayHi}>
            {t("discover.match.sayHi")}
          </Button>
          <Link
            href="/invite?source=good_match"
            className="btn btn-ghost"
            style={{ justifySelf: "stretch", textAlign: "center", textDecoration: "none" }}
            onClick={() => void trackAnalyticsEvent("viral_invite_from_match", { partner_user_id: partnerUserId ?? undefined })}
          >
            {t("discover.match.inviteFriend")}
          </Link>
          <div className="caption" style={{ textAlign: "center", opacity: 0.82, lineHeight: 1.35 }}>
            {t("discover.match.inviteHint")}
          </div>
        </div>

        <div id="discover-match-ai-openers" style={{ marginTop: 14 }}>
          <div style={{ fontWeight: 900, letterSpacing: "-0.02em" }}>✨ {t("discover.match.start.title")}</div>
          <div className="caption" style={{ marginTop: 6, opacity: 0.85, lineHeight: 1.35 }}>
            {t("discover.match.start.subtitle")}
          </div>
          <div style={{ marginTop: 10, display: "grid", gap: 10 }}>
            {suggestions.map((s) => (
              <button
                key={s.key}
                type="button"
                className="surface"
                disabled={loading}
                style={{
                  textAlign: "left",
                  padding: 12,
                  borderRadius: 16,
                  border: "1px solid rgba(255,255,255,0.12)",
                  background: "rgba(255,255,255,0.05)",
                  cursor: loading ? "default" : "pointer",
                }}
                onClick={() => {
                  if (partnerUserId != null) {
                    void trackAnalyticsEvent("ai_used", { source: "discover", surface: "match_modal_opener_pick", opener: s.key, partner_user_id: partnerUserId });
                  }
                  onStartWithDraft(s.text);
                }}
              >
                <div style={{ fontWeight: 850 }}>{s.label}</div>
                <div className="caption" style={{ marginTop: 6, opacity: 0.9, lineHeight: 1.35 }}>
                  {s.text}
                </div>
              </button>
            ))}
          </div>
        </div>

        <div style={{ marginTop: 16, display: "grid", gap: 10 }}>
          <Button type="button" variant="secondary" onClick={onClose}>
            {t("discover.match.keepSwiping")}
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function DiscoverPage() {
  const router = useRouter();
  const { t } = useT("DiscoverSwipe");
  const { t: tg } = useT("GrowthEngagement");
  const [discoverGate, setDiscoverGate] = useState<"checking" | "guest" | "user">("checking");
  useLayoutEffect(() => {
    setDiscoverGate(getToken() ? "user" : "guest");
  }, []);
  const isDevDiscoverTools =
    typeof process !== "undefined" && String(process.env.NEXT_PUBLIC_DEV_TOOLS_ENABLED || "").trim() === "1";
  const probeEmptyDiscoverDebug =
    isDevDiscoverTools || (typeof process !== "undefined" && process.env.NODE_ENV === "development");

  const [dailyReasonIdx, setDailyReasonIdx] = useState(0);
  useEffect(() => {
    setDailyReasonIdx(Math.floor(Date.now() / 86400000) % 3);
  }, []);

  const [viralCtx, setViralCtx] = useState<{
    social_proof?: { show_banner?: boolean; joining_today_count?: number };
  } | null>(null);
  useEffect(() => {
    if (!getToken()) return;
    void apiFetch("/growth/viral-context", { metaReason: "discover-viral" })
      .then((r) => {
        if (r && typeof r === "object") setViralCtx(r as { social_proof?: { show_banner?: boolean; joining_today_count?: number } });
        else setViralCtx(null);
      })
      .catch(() => setViralCtx(null));
  }, []);

  const [cards, setCards] = useState<DiscoverCard[]>([]);
  const [onboardingGate, setOnboardingGate] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [match, setMatch] = useState<
    null | {
        userId: number;
        name: string;
        photoUrl: string | null;
        isDemoProfile?: boolean;
        chatUrl: string | null;
        matchContext: AiOpenerMatchContext;
      }
  >(null);
  const [toast, setToast] = useState<string | null>(null);

  const FOMO_ACTIVE_TOAST_KEY = "neyra:retn:fomo_active_discover_v1";
  useEffect(() => {
    if (!getToken()) return;
    if (!viralCtx?.social_proof?.show_banner) return;
    const day = utcDayKey();
    if (localStorageDayShown(FOMO_ACTIVE_TOAST_KEY, day)) return;
    localStorageMarkDay(FOMO_ACTIVE_TOAST_KEY, day);
    setToast(t("retention.fomo.activeNow"));
    void trackAnalyticsEvent("retention_signal_shown", { kind: "fomo_active_now", surface: "discover" });
  }, [viralCtx?.social_proof?.show_banner, t]);

  const [resetDatingBusy, setResetDatingBusy] = useState(false);
  const [emptyFeedDebug, setEmptyFeedDebug] = useState<{
    filtered_by_pass: number;
    filtered_by_swipe: number;
    candidates_total: number;
  } | null>(null);
  const [swipeRefreshPaused, setSwipeRefreshPaused] = useState(false);
  const [undoBusy, setUndoBusy] = useState(false);
  const lastSwipeRef = useRef<null | { card: DiscoverCard; liked: boolean }>(null);
  /** Captured at swipe start; applied to `lastSwipeRef` when the deck actually slices (not when `/swipes` returns). */
  const removingForUndoRef = useRef<null | { card: DiscoverCard; liked: boolean }>(null);
  const discoverViewedRef = useRef(false);
  const lowDeckLoggedRef = useRef<string>("");
  const swipeSessionCountRef = useRef(0);

  const topCard = cards[0] ?? null;
  const topCardValid = Boolean(topCard && Number(topCard.user_id) > 0);
  /** Mobile: only top 2 stack slots — reduces overlap artifacts during rapid swipes. */
  const deckVisible = useMemo(() => cards.slice(0, 2), [cards]);

  const [viewerProfileId, setViewerProfileId] = useState<number | null>(null);
  const [demoPremiumFeedActive, setDemoPremiumFeedActive] = useState(false);
  useEffect(() => {
    if (!getToken()) return;
    let cancelled = false;
    void apiFetch("/profiles/me", { metaReason: "discover-viewer-profile", skipThrottle: true, softFail: true }).then((r: unknown) => {
      if (cancelled || !r || typeof r !== "object") return;
      const o = r as { id?: number; profile_id?: number; demo_premium_feed_active?: boolean };
      const pid = typeof o.id === "number" ? o.id : typeof o.profile_id === "number" ? o.profile_id : null;
      setViewerProfileId(pid);
      setDemoPremiumFeedActive(Boolean(o.demo_premium_feed_active));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const [swipeExit, setSwipeExit] = useState<DiscoverSwipeExitState | null>(null);
  /** Mirrors exitUiLockRef for render (refs don’t re-render) — keeps Like/Pass disabled during the pre-paint exit window on rapid mobile taps. */
  const [exitUiHold, setExitUiHold] = useState(false);
  /** True → coarse-pointer layout returns early (touch MVP). */
  const [discoverButtonOnly, setDiscoverButtonOnly] = useState(false);
  const pendingSwipeReleaseRef = useRef<{ targetId: number; action: DiscoverSwipeAction } | null>(null);
  const exitFinishHandledRef = useRef(false);
  /** Fired DISCOVER_SWIPE_ADVANCE_MS after swipe starts — removes top card even if transitionend/fly fails (fixes stuck pass + guard pending key). */
  const advanceDeckTimerRef = useRef<ReturnType<typeof globalThis.setTimeout> | null>(null);
  /**
   * Synchronous “one exit at a time” gate. React `swipeExit` updates async — rapid mobile taps could otherwise
   * start a second swipe before state commits; this ref blocks immediately until finalize/cancel/timeout clears it.
   */
  const exitUiLockRef = useRef(false);
  const stuckExitWatchdogRef = useRef<ReturnType<typeof globalThis.setTimeout> | null>(null);

  const preloadQueue = useMemo(
    () =>
      preloadDiscoverPhotoUrls(
        (c) => photosFromList(String((c as DiscoverCard).photo_urls || "")),
        cards,
        1,
        3,
      ),
    [cards],
  );

  useEffect(() => {
    preloadImages(preloadQueue);
  }, [preloadQueue]);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mqTouch = window.matchMedia("(max-width: 768px)");
    const mqCoarse = window.matchMedia("(pointer: coarse)");
    const apply = () => {
      setDiscoverButtonOnly(mqTouch.matches || mqCoarse.matches);
    };
    apply();
    mqTouch.addEventListener("change", apply);
    mqCoarse.addEventListener("change", apply);
    return () => {
      mqTouch.removeEventListener("change", apply);
      mqCoarse.removeEventListener("change", apply);
    };
  }, []);

  const loadFeed = useCallback(
    async (reason: string, opts?: { manual?: boolean }) => {
      if (!getToken()) {
        setLoading(false);
        return;
      }
      if (swipeRefreshPaused && !opts?.manual) return;
      if (opts?.manual) setSwipeRefreshPaused(false);
      setLoading(true);
      try {
        const { promise } = fetchDiscoverFeed(reason, {
          skipCache: true,
          // Manual refresh should bypass apiFetch throttle.
          skipThrottle: Boolean(opts?.manual),
        });
        const data = (await promise) as any;
        if (data && typeof data === "object" && data.onboarding_required) {
          setOnboardingGate(true);
          setCards([]);
          setEmptyFeedDebug(null);
          return;
        }
        setOnboardingGate(false);
        const arr = Array.isArray(data) ? data : Array.isArray(data?.feed) ? data.feed : Array.isArray(data?.cards) ? data.cards : [];
        const clean = (arr as DiscoverCard[]).filter((c) => c && Number(c.user_id) > 0);
        setCards(clean);
        if (clean.length > 0) setEmptyFeedDebug(null);
      } catch (e) {
        if (e instanceof ApiThrottleSkipError) {
          // Defensive: fetchDiscoverFeed already returns lastOk/[] on THROTTLE_SKIP,
          // but never let a throw crash the page.
          setCards((prev) => prev);
          return;
        }
      } finally {
        setLoading(false);
      }
    },
    [router, swipeRefreshPaused],
  );

  useEffect(() => {
    void loadFeed("discover-swipe-mount");
  }, [loadFeed]);

  useEffect(() => {
    if (discoverViewedRef.current) return;
    if (loading) return;
    discoverViewedRef.current = true;
    void trackAnalyticsEvent("discover_viewed", { source: "discover" });
  }, [loading]);

  useEffect(() => {
    if (topCard) setEmptyFeedDebug(null);
  }, [topCard]);

  useEffect(() => {
    const uid = match?.userId;
    if (!uid || uid <= 0) return;
    try {
      sessionStorage.setItem(`neyra_match_partner_ts:${uid}`, String(Date.now()));
    } catch {
      /* ignore */
    }
  }, [match?.userId]);

  useEffect(() => {
    if (loading || !topCard) return;
    if (cards.length > 2) {
      lowDeckLoggedRef.current = "";
      return;
    }
    if (cards.length < 1) return;
    const key = `${topCard.user_id}:${cards.length}`;
    if (lowDeckLoggedRef.current === key) return;
    lowDeckLoggedRef.current = key;
    void trackAnalyticsEvent("discover_low_deck_hint_shown", { surface: "discover_low_deck_candidates", remaining: cards.length });
  }, [cards, loading, topCard]);

  useEffect(() => {
    if (!probeEmptyDiscoverDebug) return;
    if (!getToken()) return;
    if (loading || topCard) return;
    let cancelled = false;
    void (async () => {
      try {
        const res = (await apiFetch("/discover/feed?limit=20&include_debug=true", {
          metaReason: "discover-empty-debug",
          skipCache: true,
          skipThrottle: true,
        })) as { feed?: unknown[]; debug?: Record<string, unknown> } | unknown[];
        if (cancelled) return;
        const payload = Array.isArray(res) ? null : res;
        const dbg = payload && typeof payload === "object" && payload.debug && typeof payload.debug === "object" ? payload.debug : null;
        if (!dbg) return;
        setEmptyFeedDebug({
          filtered_by_pass: Number(dbg.filtered_by_pass) || 0,
          filtered_by_swipe: Number(dbg.filtered_by_swipe) || 0,
          candidates_total: Number(dbg.candidates_total) || 0,
        });
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [probeEmptyDiscoverDebug, loading, topCard]);

  const swipeInteractionLocked = Boolean(swipeExit) || exitUiHold;

  const finalizeSwipeExitOnce = useCallback(() => {
    if (exitFinishHandledRef.current) return;
    exitFinishHandledRef.current = true;
    if (advanceDeckTimerRef.current) {
      clearTimeout(advanceDeckTimerRef.current);
      advanceDeckTimerRef.current = null;
    }
    if (stuckExitWatchdogRef.current) {
      clearTimeout(stuckExitWatchdogRef.current);
      stuckExitWatchdogRef.current = null;
    }
    const undoSnap = removingForUndoRef.current;
    removingForUndoRef.current = null;
    try {
      setCards((prev) => {
        const next = prev.slice(1);
        if (!swipeRefreshPaused && next.length <= 4) {
          queueMicrotask(() => void loadFeed("discover-swipe-refill"));
        }
        return next;
      });
      if (undoSnap) {
        lastSwipeRef.current = undoSnap;
        swipeSessionCountRef.current += 1;
      }
      setSwipeExit(null);
      const rel = pendingSwipeReleaseRef.current;
      pendingSwipeReleaseRef.current = null;
      if (rel) releaseDiscoverSwipe(rel.targetId, rel.action);
    } finally {
      exitUiLockRef.current = false;
      setExitUiHold(false);
    }
  }, [loadFeed, swipeRefreshPaused]);

  function cancelSwipeExitForError() {
    removingForUndoRef.current = null;
    if (advanceDeckTimerRef.current) {
      clearTimeout(advanceDeckTimerRef.current);
      advanceDeckTimerRef.current = null;
    }
    if (stuckExitWatchdogRef.current) {
      clearTimeout(stuckExitWatchdogRef.current);
      stuckExitWatchdogRef.current = null;
    }
    exitFinishHandledRef.current = false;
    setSwipeExit(null);
    const rel = pendingSwipeReleaseRef.current;
    pendingSwipeReleaseRef.current = null;
    if (rel) releaseDiscoverSwipe(rel.targetId, rel.action);
    exitUiLockRef.current = false;
    setExitUiHold(false);
  }

  /**
   * Second paint: enable CSS transition to “fly” (full exit on desktop, short nudge+fade on mobile `simple` exits).
   * Mobile drag is disabled — this path is only for programmatic exits after button/drag commit.
   */
  useLayoutEffect(() => {
    if (!swipeExit || swipeExit.fly) return;
    const id = requestAnimationFrame(() => {
      setSwipeExit((s) => (s && !s.fly ? { ...s, fly: true } : s));
    });
    return () => cancelAnimationFrame(id);
  }, [swipeExit]);

  /** Hard recovery: if exit state never clears (lost transition / timer), force slice + unlock so rapid taps cannot pile up. */
  useEffect(() => {
    if (!swipeExit) return;
    if (stuckExitWatchdogRef.current) {
      clearTimeout(stuckExitWatchdogRef.current);
      stuckExitWatchdogRef.current = null;
    }
    stuckExitWatchdogRef.current = globalThis.setTimeout(() => {
      stuckExitWatchdogRef.current = null;
      finalizeSwipeExitOnce();
    }, DISCOVER_SWIPE_STUCK_RESET_MS);
    return () => {
      if (stuckExitWatchdogRef.current) {
        clearTimeout(stuckExitWatchdogRef.current);
        stuckExitWatchdogRef.current = null;
      }
    };
  }, [swipeExit, finalizeSwipeExitOnce]);

  function onSwipeExitTransitionEnd(e: React.TransitionEvent<HTMLDivElement>) {
    if (!swipeExit?.fly) return;
    if (e.propertyName !== "transform" && e.propertyName !== "opacity") return;
    finalizeSwipeExitOnce();
  }

  /** POST `/swipes` after UI transition starts — never blocks the next card (deck slices on animation timer). */
  async function runDiscoverSwipeApi(snapshot: DiscoverCard, targetId: number, liked: boolean) {
    const swipeSignal =
      typeof AbortSignal !== "undefined" && "timeout" in AbortSignal ? AbortSignal.timeout(14_000) : undefined;
    try {
      const res = await apiFetch("/swipes", {
        method: "POST",
        metaReason: liked ? "discover-like" : "discover-pass",
        body: JSON.stringify({ target_user_id: targetId, liked }),
        signal: swipeSignal,
      });

      if (liked) {
        void trackAnalyticsEvent("like_sent", { source: "discover", target_user_id: snapshot.user_id });
      }

      if (res && typeof res === "object" && (res as any).matched) {
        void trackAnalyticsEvent("match_created", { source: "discover", partner_user_id: snapshot.user_id });
        recordMatchMoment();
        const photos = photosFromList(snapshot.photo_urls);
        const bioTrim = String(snapshot.bio || "").trim();
        const snapVibe = String(snapshot.vibe || "").trim();
        const rawLt = snapshot.lifestyle_tags;
        const ltList = Array.isArray(rawLt) ? rawLt : [];
        const tagList: string[] = [];
        if (snapVibe) tagList.push(snapVibe);
        for (const x of ltList) {
          const s = String(x || "").trim();
          if (!s || tagList.some((tg) => tg.toLowerCase() === s.toLowerCase())) continue;
          tagList.push(s);
        }
        const matchContext: AiOpenerMatchContext = {
          matchName: String(snapshot.display_name || t("discover.card.profileFallback")),
          city: snapshot.city ? String(snapshot.city) : null,
          bio: bioTrim || null,
          interests: toInterestsList(snapshot.interests),
          tags: tagList.length ? tagList : null,
        };
        setMatch({
          userId: Number(snapshot.user_id),
          name: String(snapshot.display_name || t("discover.card.profileFallback")),
          photoUrl: photos[0] || null,
          isDemoProfile: Boolean(snapshot.is_demo_profile),
          chatUrl: typeof (res as any).chat_url === "string" ? (res as any).chat_url : null,
          matchContext,
        });
        setToast(t("retention.match.dontLose"));
        void trackAnalyticsEvent("retention_signal_shown", {
          kind: "match_dont_lose",
          surface: "discover_match_modal",
          partner_user_id: Number(snapshot.user_id),
        });
      }

      if (liked) {
        recordOutboundLikeMoment();
        void (async () => {
          try {
            invalidateApiGetCache("/nav/badges");
            invalidateApiGetCache("/likes/incoming");
            invalidateApiGetCache("/matches");
            const [badges] = await Promise.all([
              apiFetch("/nav/badges", {
                metaReason: "discover-like-refresh-badges",
                skipCache: true,
                skipThrottle: true,
                softFail: true,
              }),
              apiFetch("/likes/incoming?limit=1", {
                metaReason: "discover-like-refresh-likes",
                skipCache: true,
                skipThrottle: true,
              }).catch(() => null),
              apiFetch("/matches", {
                metaReason: "discover-like-refresh-matches",
                skipCache: true,
                skipThrottle: true,
              }).catch(() => null),
              apiFetch("/messages/conversations", {
                metaReason: "discover-like-refresh-conversations",
                skipCache: true,
                skipThrottle: true,
              }).catch(() => null),
            ]);
            if (badges !== undefined) setNavBadgesFromServer(badges as any, "discover-like-refresh");
          } catch (e) {
            if (!(e instanceof ApiThrottleSkipError)) {
              /* ignore */
            }
          }
        })();
      }
    } catch (e) {
      const errName = e instanceof Error ? e.name : "";
      const isAbort = errName === "AbortError" || (e instanceof Error && /abort/i.test(e.message));

      if (e instanceof RateLimitError) {
        setSwipeRefreshPaused(true);
        cancelSwipeExitForError();
        lastSwipeRef.current = null;
        setCards((prev) => (prev[0]?.user_id === snapshot.user_id ? prev : [snapshot, ...prev]));
        setToast(t("errors.api.rateLimited"));
        return;
      }

      const msg = e instanceof Error ? e.message : String(e);
      if (liked && msg === "paywall.likes_limit") {
        cancelSwipeExitForError();
        lastSwipeRef.current = null;
        setCards((prev) => (prev[0]?.user_id === snapshot.user_id ? prev : [snapshot, ...prev]));
        if (!hasValueMoment()) {
          void trackAnalyticsEvent("paywall_deferred", { surface: "discover_likes_limit", reason: "no_value_moment" });
          setToast(t("discover.paywall.deferredToast"));
        } else {
          void trackAnalyticsEvent("paywall_shown", { surface: "discover_toast_soft", source: "discover_likes_limit" });
          setToast(t("monetization.discover.softHint"));
        }
        return;
      }

      if (isAbort) {
        setToast(t("discover.swipe.timeoutToast"));
      } else {
        setToast(t("discover.swipe.syncFailed"));
      }
    }
  }

  /**
   * Like / Pass from card buttons: optimistic deck advance, `/swipes` in background.
   */
  const advanceProfile = useCallback(
    (action: DiscoverSwipeAction) => {
      if (exitUiLockRef.current || swipeExit) return;
      const card = cards[0];
      if (!card || Number(card.user_id) <= 0) return;
      const profileId = Number(card.user_id);
      const liked = action === "like";
      if (!acquireDiscoverSwipe(profileId, action)) return;

      devDiscoverDebug({ action, profileId, deckLength: cards.length });

      const snapshot = card;
      removingForUndoRef.current = { card: snapshot, liked };
      exitFinishHandledRef.current = false;
      exitUiLockRef.current = true;
      setExitUiHold(true);
      pendingSwipeReleaseRef.current = { targetId: profileId, action };

      discoverSwipeFeedback(liked ? "like" : "pass");
      setSwipeExit({ liked, startX: 0, startY: 0, fly: false, simple: true });

      if (advanceDeckTimerRef.current) {
        clearTimeout(advanceDeckTimerRef.current);
        advanceDeckTimerRef.current = null;
      }
      advanceDeckTimerRef.current = globalThis.setTimeout(() => {
        advanceDeckTimerRef.current = null;
        finalizeSwipeExitOnce();
      }, DISCOVER_BUTTON_ADVANCE_MS);

      requestAnimationFrame(() => {
        void runDiscoverSwipeApi(snapshot, profileId, liked);
      });

      if (action === "ignore") {
        void apiFetch(`/users/${profileId}/ignore`, {
          method: "POST",
          metaReason: "discover-ignore-profile",
          body: JSON.stringify({}),
          softFail: true,
        })
          .then(() => {
            void trackAnalyticsEvent("discover_profile_ignored", { target_user_id: profileId, surface: "discover" });
          })
          .catch(() => {
            void trackAnalyticsEvent("discover_profile_ignored_local_only", { target_user_id: profileId, surface: "discover" });
          });
      }
    },
    [cards, swipeExit, finalizeSwipeExitOnce],
  );

  async function undoSwipe() {
    if (exitUiLockRef.current || swipeExit) return;
    const last = lastSwipeRef.current;
    if (!last || undoBusy) return;
    setUndoBusy(true);
    try {
      await apiFetch("/swipes/undo", { method: "POST", metaReason: "discover-undo" });
      setCards((prev) => [last.card, ...prev]);
      lastSwipeRef.current = null;
    } catch {
      setToast(t("discover.swipe.syncFailed"));
    } finally {
      setUndoBusy(false);
    }
  }

  async function activateBoost() {
    if (busy) return;
    setBusy(true);
    try {
      await apiFetch("/growth/boost/activate", {
        method: "POST",
        metaReason: "boost-activate",
        body: JSON.stringify({}),
      });
      setToast(t("discover.boost.activeToast"));
      void trackAnalyticsEvent("boost_activated", { surface: "discover" });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg === "paywall.boost_requires_premium") {
        void trackAnalyticsEvent("paywall_shown", { surface: "discover_boost", source: "boost_requires_premium" });
        router.push("/premium?source=discover_boost");
        setToast(t("monetization.discover.softHint"));
      } else {
        void trackAnalyticsEvent("boost_activate_failed", { surface: "discover", error: msg.slice(0, 120) });
        setToast(t("common.tryAgain"));
      }
    } finally {
      setBusy(false);
    }
  }

  async function ignoreCurrentProfile() {
    if (swipeInteractionLocked) return;
    void advanceProfile("ignore");
    setToast(t("discover.actions.ignoredToast"));
  }

  /** Bundled demo photo failed twice — drop card and sync pass without blocking UX. */
  const swipeAwayBrokenPhoto = useCallback(() => {
    setCards((prev) => {
      const snap = prev[0];
      if (!snap || Number(snap.user_id) <= 0) return prev;
      const uid = Number(snap.user_id);
      void apiFetch("/swipes", {
        method: "POST",
        metaReason: "discover-pass-broken-photo",
        body: JSON.stringify({ target_user_id: uid, liked: false }),
        softFail: true,
      }).catch(() => {});
      void trackAnalyticsEvent("discover_demo_photo_dropped", { target_user_id: uid, surface: "discover" });
      const next = prev.slice(1);
      if (!swipeRefreshPaused && next.length <= 4) {
        queueMicrotask(() => void loadFeed("discover-after-photo-drop"));
      }
      return next;
    });
  }, [loadFeed, swipeRefreshPaused]);

  const maxRot = 12;
  const rotDiv = 18;
  const exiting = Boolean(swipeExit);
  const exitFly = Boolean(swipeExit?.fly);
  const simpleExit = Boolean(swipeExit?.simple);
  let cardTransform: string;
  let cardOpacity = 1;
  if (exiting && swipeExit && simpleExit) {
    if (!exitFly) {
      cardTransform = "translate3d(0,0,0)";
      cardOpacity = 1;
    } else {
      const nudge = 28;
      const tx = swipeExit.liked ? nudge : -nudge;
      cardTransform = `translate3d(${tx}px, 0, 0)`;
      cardOpacity = 0;
    }
  } else if (exiting && swipeExit) {
    if (!exitFly) {
      const sx = swipeExit.startX;
      const sy = swipeExit.startY;
      const r = clamp(sx / rotDiv, -maxRot, maxRot);
      cardTransform = `translate3d(${sx}px, ${sy}px, 0) rotate(${r}deg)`;
    } else {
      const xw = swipeExit.liked ? "120vw" : "-120vw";
      const yfly = swipeExit.startY * 0.12;
      const endRot = swipeExit.liked ? 3.5 : -3.5;
      cardTransform = `translate3d(${xw}, ${yfly}px, 0) rotate(${endRot}deg)`;
      cardOpacity = 0;
    }
  } else {
    cardTransform = "translate3d(0,0,0)";
  }
  const cardTransition =
    exiting && simpleExit && exitFly
      ? `transform ${DISCOVER_BUTTON_EXIT_MS}ms ease-out, opacity ${DISCOVER_BUTTON_EXIT_MS}ms ease-out`
      : exiting && simpleExit && !exitFly
        ? "none"
        : exiting && exitFly && !simpleExit
          ? `transform ${DISCOVER_SWIPE_EXIT_MS}ms cubic-bezier(0.22, 1, 0.36, 1), opacity ${DISCOVER_SWIPE_EXIT_MS}ms ease`
          : exiting && !exitFly && !simpleExit
            ? "none"
            : "transform 340ms cubic-bezier(0.22, 1, 0.36, 1)";
  const lowDeckCandidates = Boolean(
    !loading &&
      topCardValid &&
      cards.length <= 2 &&
      cards.length > 0 &&
      swipeSessionCountRef.current >= 8 &&
      !isDevDiscoverTools &&
      !probeEmptyDiscoverDebug,
  );

  if (discoverGate === "checking") {
    return (
      <PageShell className="discover-swipe-shell">
        <div className="body muted" style={{ padding: 24 }}>
          {t("common.loading")}
        </div>
      </PageShell>
    );
  }
  if (discoverGate === "guest") {
    return <DiscoverGuestPreview />;
  }

  if (discoverButtonOnly) {
    const mobileMainPhoto = topCard ? resolveDemoProfilePhoto(topCard) : "";
    const mobileName = String(topCard?.display_name || t("discover.card.profileFallback")).trim();
    const mobileAge = topCard?.age != null ? `, ${topCard.age}` : "";
    const mobileCity = String(topCard?.city || "").trim();
    return (
      <PageShell className="discover-swipe-shell">
        <Toast text={toast || ""} onClose={() => setToast(null)} />
        <div style={{ paddingBottom: "calc(260px + env(safe-area-inset-bottom, 0px))" }}>
          <div style={{ marginBottom: 12 }}>
            <div className="caption" style={{ opacity: 0.82 }}>
              {t("discover.swipe.tip")}
            </div>
          </div>
          {loading ? (
            <div className="surface" style={{ borderRadius: 20, minHeight: 420, background: "rgba(255,255,255,0.05)" }} />
          ) : !topCardValid ? (
            <div className="surface" style={{ borderRadius: 20, padding: 18 }}>
              <div className="h2" style={{ fontSize: 20 }}>{t("discover.empty.title")}</div>
              <div className="subtitle" style={{ marginTop: 8, opacity: 0.85 }}>{t("discover.empty.description")}</div>
              <div style={{ marginTop: 12 }}>
                <Button type="button" variant="secondary" onClick={() => void loadFeed("discover-swipe-refresh", { manual: true })}>
                  {t("discover.empty.refresh")}
                </Button>
              </div>
            </div>
          ) : (
            <div className="discover-mobile-embed-card">
              <article className="surface discover-mobile-mvp-card">
                <div className="discover-mobile-mvp-card__photo-wrap">
                  {mobileMainPhoto ? (
                    <img
                      data-testid="discover-photo"
                      className="discover-mobile-mvp-card__photo"
                      src={mobileMainPhoto}
                      alt={mobileName}
                      loading="eager"
                    />
                  ) : (
                    <div className="discover-mobile-mvp-card__photo-fallback" />
                  )}
                </div>
                <div className="discover-mobile-mvp-card__meta">
                  <div className="discover-mobile-mvp-card__name">
                    {mobileName}
                    {mobileAge}
                  </div>
                  {mobileCity ? <div className="discover-mobile-mvp-card__city">{mobileCity}</div> : null}
                  <button type="button" className="discover-detail-link" onClick={() => router.push(`/people/${topCard.user_id}`)}>
                    {t("discover.card.fullProfile")}
                  </button>
                </div>
              </article>
            </div>
          )}
          <div className="discover-actions-mvp">
            <div className="discover-actions-mvp__row">
              <Button
                type="button"
                className="discover-action-tap discover-action-tap--like discover-action-tap--mvp"
                disabled={swipeInteractionLocked || !topCardValid}
                onClick={() => void advanceProfile("like")}
              >
                ❤️ {t("discover.actions.like")}
              </Button>
              <Button
                type="button"
                variant="secondary"
                className="discover-action-tap discover-action-tap--pass discover-action-tap--mvp"
                disabled={swipeInteractionLocked || !topCardValid}
                onClick={() => void advanceProfile("pass")}
              >
                ✖ {t("discover.actions.pass")}
              </Button>
            </div>
            <Button
              type="button"
              variant="secondary"
              className="discover-action-tap discover-action-tap--ignore discover-action-tap--mvp"
              disabled={swipeInteractionLocked || !topCardValid}
              onClick={() => void advanceProfile("ignore")}
            >
              🚫 {t("discover.actions.ignore")}
            </Button>
            <Button
              type="button"
              variant="secondary"
              className="discover-action-tap discover-action-tap--boost discover-action-tap--mvp"
              disabled={busy || swipeInteractionLocked || !topCardValid}
              onClick={() => void activateBoost()}
            >
              ⭐ {t("discover.actions.boostProfile")}
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="discover-action-tap discover-action-tap--sub discover-action-tap--mvp"
              disabled={undoBusy || !lastSwipeRef.current || swipeInteractionLocked}
              onClick={() => void undoSwipe()}
            >
              {t("discover.actions.undo")}
            </Button>
          </div>
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell className="discover-swipe-shell">
      <Toast text={toast || ""} onClose={() => setToast(null)} />
      {getToken() ? (
        <div style={{ maxWidth: 900, margin: "0 auto", padding: "0 14px 12px", textAlign: "center" }}>
          <div className="body" style={{ opacity: 0.88 }}>
            {tg((["growth.daily.reason0", "growth.daily.reason1", "growth.daily.reason2"] as const)[dailyReasonIdx])}
          </div>
          {viralCtx?.social_proof?.show_banner ? (
            <div className="body" style={{ marginTop: 10, opacity: 0.92, fontWeight: 800 }}>
              {tg("growth.social.matchingNow")}
              {typeof viralCtx.social_proof?.joining_today_count === "number" && viralCtx.social_proof.joining_today_count > 0 ? (
                <span className="caption" style={{ fontWeight: 650, opacity: 0.9 }}>
                  {" "}
                  (+{viralCtx.social_proof.joining_today_count})
                </span>
              ) : null}
            </div>
          ) : null}
          <div className="caption" style={{ marginTop: 8, opacity: 0.78, maxWidth: "52ch", marginLeft: "auto", marginRight: "auto", lineHeight: 1.4 }}>
            {tg("growth.social.repliesFast")}
          </div>
        </div>
      ) : null}
      <MatchModal
        open={Boolean(match)}
        name={match?.name || ""}
        photoUrl={
          match?.photoUrl
            ? resolveDemoProfilePhoto({ is_demo_profile: Boolean(match.isDemoProfile), photo_url: match.photoUrl })
            : null
        }
        partnerUserId={match?.userId ?? null}
        matchContext={match?.matchContext ?? null}
        t={t}
        onSayHi={() => {
          const url = match?.chatUrl;
          setMatch(null);
          if (url) router.push(url);
        }}
        onStartWithDraft={(draft) => {
          const base = (match?.chatUrl || (match?.userId ? `/chat/${match.userId}` : "/chat")) as string;
          const u = new URL(base, typeof window !== "undefined" ? window.location.origin : "http://localhost");
          u.searchParams.set("draft", String(draft || "").trim());
          u.searchParams.set("quick_send", "1");
          u.searchParams.set("focus", "1");
          setMatch(null);
          router.push(u.pathname + u.search);
        }}
        onClose={() => setMatch(null)}
      />

      <div style={{ maxWidth: 520, margin: "0 auto", width: "100%", padding: "10px 14px 0" }}>
        <div className="h2" style={{ fontSize: 22, fontWeight: 950, letterSpacing: "-0.03em" }}>
          {t("discover.header.title")}
        </div>
        <div className="subtitle" style={{ marginTop: 6, opacity: 0.8 }}>
          {t("discover.header.subtitle")}
        </div>
      </div>

      {lowDeckCandidates ? (
        <div style={{ maxWidth: 520, margin: "10px auto 0", padding: "0 14px", width: "100%" }}>
          <div
            className="surface"
            role="note"
            style={{
              padding: "12px 14px",
              borderRadius: 16,
              border: "1px solid rgba(255, 167, 120, 0.25)",
              background: "linear-gradient(145deg, rgba(255, 146, 90, 0.12), rgba(124, 92, 255, 0.08))",
              lineHeight: 1.4,
            }}
          >
            <div style={{ fontWeight: 900, letterSpacing: "-0.02em" }}>{t("discover.lowDeck.title")}</div>
            <div className="caption" style={{ marginTop: 6, opacity: 0.88 }}>
              {t("discover.lowDeck.body")}
            </div>
            <div style={{ marginTop: 10 }}>
              <Button
                type="button"
                variant="secondary"
                disabled={busy}
                onClick={() => {
                  void trackAnalyticsEvent("paywall_clicked", { surface: "discover_low_deck_boost" });
                  void activateBoost();
                }}
              >
                {t("discover.lowDeck.ctaBoost")}
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {!loading && topCard?.discover_fallback_used ? (
        <div
          role="status"
          style={{
            maxWidth: 520,
            margin: "10px auto 0",
            padding: "10px 14px",
            width: "100%",
            borderRadius: 14,
            background: "rgba(255,255,255,0.06)",
            border: "1px solid rgba(255,255,255,0.12)",
          }}
        >
          <div className="caption" style={{ opacity: 0.9, lineHeight: 1.45, fontWeight: 650 }}>
            {t("discover.fallbackPreferencesHint")}
          </div>
        </div>
      ) : null}

      <div className="discover-swipe-column">
        {/* Stage clips translated cards; column keeps actions visually below the deck (not under it). */}
        <div className="discover-swipe-stage">
          <div
            className="discover-swipe-viewport"
            style={{ pointerEvents: swipeInteractionLocked ? "none" : undefined }}
          >
          {loading ? (
            <div className="surface" style={{ width: "100%", height: "100%", borderRadius: 22, background: "rgba(255,255,255,0.06)" }} />
          ) : onboardingGate ? (
            <div className="surface" style={{ width: "100%", height: "100%", borderRadius: 22, display: "grid", placeItems: "center", padding: 18 }}>
              <div style={{ textAlign: "center", maxWidth: 420 }}>
                <div className="h2" style={{ fontSize: 18, fontWeight: 900 }}>
                  {t("discover.onboardingGate.title")}
                </div>
                <div className="subtitle" style={{ marginTop: 10, opacity: 0.88, lineHeight: 1.45 }}>
                  {t("discover.onboardingGate.body")}
                </div>
                <div style={{ marginTop: 16 }}>
                  <Button type="button" onClick={() => router.push("/onboarding")}>
                    {t("discover.onboardingGate.cta")}
                  </Button>
                </div>
                <div style={{ marginTop: 12 }}>
                  <Button type="button" variant="ghost" onClick={() => router.push("/profile")}>
                    {t("discover.empty.editProfile")}
                  </Button>
                </div>
              </div>
            </div>
          ) : !topCardValid ? (
            <div className="surface" style={{ width: "100%", height: "100%", borderRadius: 22, display: "grid", placeItems: "center", padding: 18 }}>
              <div style={{ textAlign: "center" }}>
                <div className="h2" style={{ fontSize: 18, fontWeight: 900 }}>
                  {t("discover.empty.title")}
                </div>
                <div className="subtitle" style={{ marginTop: 8, opacity: 0.85 }}>
                  {emptyFeedDebug && isHeavySwipePassEmptyHint(emptyFeedDebug)
                    ? t("discover.empty.reasonHeavySwipePass")
                    : t("discover.empty.description")}
                </div>
              </div>
              <div style={{ marginTop: 12 }}>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "center" }}>
                  <Button type="button" variant="secondary" onClick={() => void loadFeed("discover-swipe-refresh", { manual: true })}>
                    {t("discover.empty.refresh")}
                  </Button>
                  {isDevDiscoverTools ? (
                    <Button
                      type="button"
                      variant="secondary"
                      disabled={resetDatingBusy}
                      onClick={async () => {
                        if (resetDatingBusy) return;
                        setResetDatingBusy(true);
                        try {
                          await apiFetch("/dev/reset-dating-state", {
                            method: "POST",
                            metaReason: "discover-reset-dating-state",
                            skipThrottle: true,
                            skipCache: true,
                          });
                          invalidateApiGetCache("/nav/badges");
                          invalidateApiGetCache("/likes/incoming");
                          invalidateApiGetCache("/matches");
                          invalidateApiGetCache("/discover/feed");
                          const [badges] = await Promise.all([
                            apiFetch("/nav/badges", {
                              metaReason: "discover-reset-dating-nav",
                              skipCache: true,
                              skipThrottle: true,
                              softFail: true,
                            }),
                            apiFetch("/likes/incoming?limit=24", {
                              metaReason: "discover-reset-dating-likes",
                              skipCache: true,
                              skipThrottle: true,
                            }).catch(() => null),
                            apiFetch("/matches", {
                              metaReason: "discover-reset-dating-matches",
                              skipCache: true,
                              skipThrottle: true,
                            }).catch(() => null),
                          ]);
                          if (badges !== undefined) setNavBadgesFromServer(badges as any, "discover-reset-dating-state");
                          setToast(t("discover.empty.toastTestSwipesReset"));
                          setEmptyFeedDebug(null);
                          void loadFeed("discover-after-reset-dating-state", { manual: true });
                        } catch {
                          /* ignore */
                        } finally {
                          setResetDatingBusy(false);
                        }
                      }}
                    >
                      {t("discover.empty.resetTestSwipes")}
                    </Button>
                  ) : null}
                </div>
              </div>
              <div style={{ marginTop: 14, textAlign: "center", maxWidth: 420 }}>
                <div className="caption" style={{ opacity: 0.84, lineHeight: 1.45 }}>
                  {t("discover.empty.guidanceTitle")}
                </div>
                <div style={{ marginTop: 10, display: "grid", gap: 8 }}>
                  <div className="caption" style={{ opacity: 0.82 }}>
                    • {t("discover.empty.guidance.profile")}
                  </div>
                  <div className="caption" style={{ opacity: 0.82 }}>
                    • {t("discover.empty.guidance.preferences")}
                  </div>
                  <div className="caption" style={{ opacity: 0.82 }}>
                    • {t("discover.empty.guidance.checkBack")}
                  </div>
                </div>
                <div style={{ marginTop: 12, display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "center" }}>
                  <Button type="button" variant="ghost" onClick={() => router.push("/profile")}>
                    {t("discover.empty.editProfile")}
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => router.push("/onboarding")}>
                    {t("discover.empty.adjustPreferences")}
                  </Button>
                </div>
              </div>
            </div>
          ) : (
            <>
              {!discoverButtonOnly && deckVisible[1] ? (
                <div
                  className="surface"
                  aria-hidden
                  style={{
                    position: "absolute",
                    inset: 0,
                    zIndex: 0,
                    borderRadius: 22,
                    transform: "scale(0.985) translateY(6px)",
                    background: "rgba(255,255,255,0.05)",
                  }}
                />
              ) : null}

              <div
                className="surface discover-embed-card-wrap"
                onTransitionEnd={onSwipeExitTransitionEnd}
                style={{
                  position: "absolute",
                  inset: 0,
                  zIndex: exiting ? 12 : 2,
                  borderRadius: 22,
                  overflow: "auto",
                  touchAction: "manipulation",
                  transform: cardTransform,
                  opacity: cardOpacity,
                  transition: cardTransition,
                  willChange: exiting ? "transform, opacity" : "transform",
                  pointerEvents: swipeInteractionLocked ? "none" : "auto",
                  background: "transparent",
                  border: "none",
                }}
              >
                {topCard ? (
                  <DiscoverProfileCard
                    card={mapDiscoverCardToProfileData(topCard, demoPremiumFeedActive)}
                    planTier="free"
                    viewerProfileId={viewerProfileId}
                    disabled={swipeInteractionLocked}
                    exiting={swipeExit ? { liked: swipeExit.liked } : null}
                    onLike={() => void advanceProfile("like")}
                    onPass={() => void advanceProfile("pass")}
                    onIgnore={() => void ignoreCurrentProfile()}
                    onPeek={() => router.push(`/people/${topCard.user_id}`)}
                    onMediaFatal={swipeAwayBrokenPhoto}
                  />
                ) : null}
              </div>
            </>
          )}
          </div>
        </div>

        {!loading &&
        topCardValid &&
        !demoPremiumFeedActive &&
        !topCard?.is_demo_profile &&
        !topCard?.discover_missing_photo ? (
          <div className="caption" style={{ marginTop: 12, textAlign: "center", opacity: 0.82, lineHeight: 1.4 }}>
            💡 {t("discover.swipe.verifiedRespondMore")}
          </div>
        ) : null}

        <div className="discover-swipe-actions discover-swipe-actions--desktop">
          <div className="discover-actions-desktop discover-actions-desktop--primary">
            <Button
              type="button"
              variant="secondary"
              className="discover-action-tap discover-action-tap--pass"
              disabled={swipeInteractionLocked || !topCardValid}
              onClick={() => void advanceProfile("pass")}
            >
              {t("discover.card.pass")}
            </Button>
            <Button
              type="button"
              variant="secondary"
              className="discover-action-tap discover-action-tap--ignore"
              disabled={swipeInteractionLocked || !topCardValid}
              onClick={() => void ignoreCurrentProfile()}
            >
              {t("discover.actions.ignore")}
            </Button>
            <Button
              type="button"
              className="discover-action-tap discover-action-tap--like"
              disabled={swipeInteractionLocked || !topCardValid}
              onClick={() => void advanceProfile("like")}
            >
              {t("discover.card.like")}
            </Button>
          </div>
          <div className="discover-actions-desktop discover-actions-desktop--secondary">
            <Button
              type="button"
              variant="secondary"
              className="discover-action-tap"
              disabled={undoBusy || !lastSwipeRef.current || swipeInteractionLocked}
              onClick={() => void undoSwipe()}
            >
              ↩ {t("discover.actions.undo")}
            </Button>
            <Button
              type="button"
              variant="secondary"
              className="discover-action-tap"
              disabled={busy || swipeInteractionLocked || !topCardValid}
              onClick={() => void activateBoost()}
            >
              ⭐ {t("discover.actions.boostProfile")}
            </Button>
          </div>
        </div>
      </div>
    </PageShell>
  );
}
