"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { getToken } from "../../../lib/api";
import { markAppFirstUseNow } from "../../../lib/reviewPrompt";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { localStorageDayShown, localStorageMarkDay, utcDayKey } from "../../../lib/retention/dedupe";
import type { NavBadgesResponse } from "../../../lib/nav-config";
import { getNavBadgesSnapshot, subscribeNavBadges } from "../../../lib/navBadgesStore";
import { useT } from "../i18n/I18nProvider";
import { Toast } from "../ui";

const ACTIVITY_KEY = "neyra:last_client_activity_at";
const RETURN_TOAST_KEY = "neyra:last_return_toast_date";
const LIKE_TOAST_KEY = "neyra:last_like_nudge_incoming";
const DAILY_PROFILES_TOAST_KEY = "neyra:retn:daily_profiles_toast_v1";

/**
 * Lightweight retention hooks: activity timestamp, 24h return nudge, incoming-like nudge,
 * daily “new profiles” reminder (once/day, deduped), session telemetry.
 */
export function GrowthEngagementLayer() {
  const pathname = usePathname() || "/";
  const { t } = useT("GrowthEngagement");
  const [toast, setToast] = useState<string | null>(null);
  const prevBadgesRef = useRef<NavBadgesResponse | null>(null);
  const returnCheckedRef = useRef(false);
  const dailyProfilesScheduledRef = useRef(false);
  const sessionStartedRef = useRef(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!getToken()) return;
    if (returnCheckedRef.current) return;
    returnCheckedRef.current = true;
    try {
      const raw = localStorage.getItem(ACTIVITY_KEY);
      const last = raw ? Number(raw) : 0;
      if (!last || last <= 0) {
        localStorage.setItem(ACTIVITY_KEY, String(Date.now()));
        return;
      }
      const idleMs = Date.now() - last;
      const dayKey = new Date().toISOString().slice(0, 10);
      const lastToast = localStorage.getItem(RETURN_TOAST_KEY) || "";
      if (idleMs < 24 * 60 * 60 * 1000) return;
      if (lastToast === dayKey) return;
      localStorage.setItem(RETURN_TOAST_KEY, dayKey);
      void trackAnalyticsEvent("reengagement_return_prompt", { source: "idle_24h", surface: "toast" });
      void trackAnalyticsEvent("retention_signal_shown", { kind: "idle_return_24h", surface: "toast" });
      setToast(t("growth.return.replyWaiting"));
    } catch {
      /* ignore */
    }
  }, [t]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!getToken()) return;
    const p = pathname || "/";
    if (p.startsWith("/onboarding") || p.startsWith("/intro") || p.startsWith("/login") || p.startsWith("/signup")) return;
    markAppFirstUseNow();
  }, [pathname]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!getToken()) return;
    if (sessionStartedRef.current) return;
    sessionStartedRef.current = true;
    let sid = "";
    try {
      sid = sessionStorage.getItem("neyra:session_id") || "";
      if (!sid) {
        sid = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `s_${Date.now()}`;
        sessionStorage.setItem("neyra:session_id", sid);
      }
    } catch {
      sid = `s_${Date.now()}`;
    }
    void trackAnalyticsEvent("retention_session_start", { session_id: sid, path: pathname });
  }, [pathname]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!getToken()) return;
    if (dailyProfilesScheduledRef.current) return;
    dailyProfilesScheduledRef.current = true;
    const timer = window.setTimeout(() => {
      try {
        const p = window.location.pathname || "/";
        if (p.startsWith("/onboarding") || p.startsWith("/intro")) return;
        const day = utcDayKey();
        if (localStorageDayShown(DAILY_PROFILES_TOAST_KEY, day)) return;
        localStorageMarkDay(DAILY_PROFILES_TOAST_KEY, day);
        void trackAnalyticsEvent("retention_signal_shown", { kind: "daily_new_profiles", surface: "toast" });
        setToast(t("retention.daily.newProfiles"));
      } catch {
        /* ignore */
      }
    }, 5200);
    return () => window.clearTimeout(timer);
  }, [t]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      localStorage.setItem(ACTIVITY_KEY, String(Date.now()));
    } catch {
      /* ignore */
    }
  }, [pathname]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!getToken()) return;
    const onVis = () => {
      try {
        localStorage.setItem(ACTIVITY_KEY, String(Date.now()));
      } catch {
        /* ignore */
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    const snap = getNavBadgesSnapshot();
    if (snap) prevBadgesRef.current = snap;
    return subscribeNavBadges(() => {
      const next = getNavBadgesSnapshot();
      if (!next) return;
      const prev = prevBadgesRef.current;
      prevBadgesRef.current = next;
      if (!prev) return;

      const dayKey = new Date().toISOString().slice(0, 10);

      const nm = next.new_matches ?? 0;
      const pm = prev.new_matches ?? 0;
      if (nm > pm) {
        try {
          const gate = `${dayKey}:${nm}`;
          if (localStorage.getItem("neyra:last_new_match_toast_v1") === gate) return;
          localStorage.setItem("neyra:last_new_match_toast_v1", gate);
        } catch {
          /* ignore */
        }
        void trackAnalyticsEvent("reengagement_match_notification", { surface: "toast", new_matches: nm });
        void trackAnalyticsEvent("retention_signal_shown", { kind: "new_match_nav", surface: "toast", new_matches: nm });
        setToast(t("growth.notify.newMatch"));
        return;
      }

      const il = next.incoming_likes ?? 0;
      const pil = prev.incoming_likes ?? 0;
      if (il > pil) {
        try {
          const payload = `${dayKey}:${il}`;
          const last = localStorage.getItem(LIKE_TOAST_KEY) || "";
          if (last === payload) return;
          localStorage.setItem(LIKE_TOAST_KEY, payload);
        } catch {
          /* ignore */
        }
        void trackAnalyticsEvent("reengagement_like_notification", { source: "likes", surface: "toast", incoming_likes: il });
        void trackAnalyticsEvent("retention_signal_shown", { kind: "fomo_someone_liked", surface: "toast", incoming_likes: il });
        setToast(t("retention.fomo.someoneLikedYou"));
        return;
      }

      const cu = next.chat_threads_unread ?? 0;
      const pcu = prev.chat_threads_unread ?? 0;
      if (cu > pcu && cu >= 2) {
        try {
          const last = localStorage.getItem("neyra:last_chat_heat_toast_v1") || "";
          if (last === dayKey) return;
          localStorage.setItem("neyra:last_chat_heat_toast_v1", dayKey);
        } catch {
          /* ignore */
        }
        void trackAnalyticsEvent("reengagement_chat_activity", { surface: "toast", chat_threads_unread: cu });
        void trackAnalyticsEvent("retention_signal_shown", { kind: "chat_heating_up", surface: "toast", chat_threads_unread: cu });
        setToast(t("growth.notify.chatHeatingUp"));
      }
    });
  }, [t]);

  return <Toast text={toast} onClose={() => setToast(null)} />;
}
