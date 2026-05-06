"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { apiFetch, getToken } from "../../../lib/api";
import { AI_DEBUG_ENABLED, FORCE_AI_VISIBLE, logAiGate } from "../../../lib/aiDebug";
import { renderDiscoverReason } from "../../../lib/aiSurfaceCopy";
import { debugChat } from "../../../lib/chat/debug";
import { fetchCompatibilityScoresBatch, type CompatibilityScore } from "../../../lib/compatibility/api";
import { setChatThreadHeaderSeed } from "../../../lib/chat/threadHeaderSeed";
import { getAiOpeners, sendThreadMessage } from "../../../lib/chat/api";
import { i18nKey, resolveI18nText, type I18nText } from "../../../lib/i18n/message";
import { MATCHES_MARK_SEEN_EVENT, isMatchesNewBadgeDismissedForPartner, pruneDismissedMatchesNewBadges } from "../../../lib/matchesNewBadge";
import { consumeNextPageToast } from "../../../lib/nextPageToast";
import { queueNextPageToast } from "../../../lib/nextPageToast";
import { PAGE_BOOT_FETCH_DELAY_MS, PAGE_SECONDARY_FETCH_DELAY_MS, schedulePageLoad } from "../../../lib/pageLoad";
import { resolveMediaUrl } from "../../../lib/media";
import { resolvePhoto } from "../../../lib/resolvePhoto";
import { AiDebugPill } from "../../components/AiDebugPill";
import { EmptyState } from "../../components/EmptyState";
import { useT } from "../../components/i18n/I18nProvider";
import { PageHeader } from "../../components/PageHeader";
import { PageShell } from "../../components/PageShell";
import { SafeImg } from "../../components/SafeImg";
import { LikesYouPanel } from "../../components/likes/LikesYouPanel";
import { PremiumBadge } from "../../components/trust/PremiumBadge";
import { VerifiedBadge } from "../../components/trust/VerifiedBadge";
import { Badge, Button, Card, Skeleton, Toast } from "../../components/ui";

type MatchRow = {
  match_id: number;
  partner_user_id: number;
  conversation_id?: number;
  partner_display_name: string;
  partner_age: number | null;
  partner_city: string;
  partner_photo: string | null;
  partner_verified?: boolean;
  partner_is_premium?: boolean;
  matched_at?: string | null;
  is_new_match?: boolean;
  last_message_preview?: string | null;
  last_message_at?: string | null;
  partner_profile?: { display_name: string; age: number | null; city: string; photo_url: string | null };
};

type ConvoRow = {
  partner_user_id: number;
  last_message_preview: string;
  last_message_at: string | null;
  unread_count?: number;
};

export default function MatchesPage() {
  const router = useRouter();
  const pathname = usePathname() || "";
  const { t, locale } = useT("MatchesPage");
  const [matches, setMatches] = useState<MatchRow[]>([]);
  const [convos, setConvos] = useState<ConvoRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<I18nText>(null);
  const [toast, setToast] = useState<I18nText>(null);
  const [viewerProfileId, setViewerProfileId] = useState<number | null>(null);
  const [compatByPartnerId, setCompatByPartnerId] = useState<Map<number, CompatibilityScore>>(() => new Map());
  const [hasLikesPreview, setHasLikesPreview] = useState<boolean>(false);
  const [likesIncomingStats, setLikesIncomingStats] = useState<{ today: number; waiting: number } | null>(null);
  const [openerByPartnerId, setOpenerByPartnerId] = useState<Map<number, { variants: string[]; bestIndex: number }>>(() => new Map());
  const [sendingByPartnerId, setSendingByPartnerId] = useState<Map<number, boolean>>(() => new Map());
  const bootStartedRef = useRef(false);
  const previewLoadCancelRef = useRef<(() => void) | null>(null);
  const liveActivityLoggedRef = useRef(false);
  const prevPathnameRef = useRef<string | null>(null);

  useEffect(() => {
    setOpenerByPartnerId(new Map());
  }, [locale]);

  const matchesLoadMessage = useCallback(
    (error: unknown): NonNullable<I18nText> => {
      if (error instanceof Error && error.name === "RateLimitError") {
        return i18nKey("matches.errors.rateLimit");
      }
      return i18nKey("matches.errors.load");
    },
    [],
  );

  useEffect(() => {
    const nextToast = consumeNextPageToast();
    if (nextToast) setToast(nextToast);
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    let cancelled = false;
    void apiFetch("/likes/incoming?limit=1", { metaReason: "matches-likes-stats", skipThrottle: true })
      .then((raw) => {
        if (cancelled) return;
        const o = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
        setLikesIncomingStats({
          today: Math.max(0, Math.trunc(Number(o.today_count ?? 0))),
          waiting: Math.max(0, Math.trunc(Number(o.waiting_count ?? 0))),
        });
      })
      .catch(() => {
        if (!cancelled) setLikesIncomingStats(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    let cancelled = false;
    void apiFetch("/profiles/me", { metaReason: "matches-viewer-profile", skipThrottle: true })
      .then((profile) => {
        if (cancelled) return;
        const id = Math.trunc(Number(profile && typeof profile === "object" ? (profile as any).id : 0));
        setViewerProfileId(Number.isFinite(id) && id > 0 ? id : null);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const loadMatchRows = useCallback(
    async (reason: string, opts?: { background?: boolean; forceFresh?: boolean }) => {
      if (!getToken()) {
        router.replace("/login");
        return;
      }
      if (!opts?.background) {
        setLoadError(null);
        setLoading(true);
      }
      try {
        const result = await apiFetch("/matches", {
          metaReason: reason,
          skipCache: opts?.forceFresh === true,
          skipThrottle: opts?.forceFresh === true,
        });
        const nextMatches = Array.isArray(result) ? (result as MatchRow[]) : [];
        pruneDismissedMatchesNewBadges(nextMatches);
        setMatches(nextMatches);
      } catch (errorValue) {
        if (!opts?.background) {
          setLoadError(matchesLoadMessage(errorValue));
          setMatches([]);
        }
      } finally {
        if (!opts?.background) setLoading(false);
      }
    },
    [router, matchesLoadMessage],
  );

  const loadConversationPreviews = useCallback(
    async (reason: string, opts?: { forceFresh?: boolean }) => {
      if (!getToken()) return;
      try {
        const result = await apiFetch("/messages/conversations", {
          metaReason: reason,
          skipCache: opts?.forceFresh === true,
          skipThrottle: opts?.forceFresh === true,
        });
        setConvos(Array.isArray(result) ? (result as ConvoRow[]) : []);
      } catch {
        /* ignore */
      }
    },
    [],
  );

  const queueConversationPreviews = useCallback(
    (reason: string, opts?: { forceFresh?: boolean; delayMs?: number }) => {
      previewLoadCancelRef.current?.();
      previewLoadCancelRef.current = schedulePageLoad(() => {
        previewLoadCancelRef.current = null;
        void loadConversationPreviews(reason, opts);
      }, opts?.delayMs ?? PAGE_SECONDARY_FETCH_DELAY_MS);
    },
    [loadConversationPreviews],
  );

  useEffect(() => {
    if (!getToken()) return;
    const prev = prevPathnameRef.current;
    prevPathnameRef.current = pathname;
    if (pathname !== "/matches") return;
    if (prev != null && prev !== "/matches") {
      void loadMatchRows("matches-route-enter", { background: true, forceFresh: true });
      queueConversationPreviews("matches-route-enter-previews", { forceFresh: true, delayMs: PAGE_BOOT_FETCH_DELAY_MS });
    }
  }, [pathname, loadMatchRows, queueConversationPreviews]);

  useEffect(() => {
    if (bootStartedRef.current) return;
    bootStartedRef.current = true;

    const cancelBootLoad = schedulePageLoad(() => {
      void loadMatchRows("matches-page");
    }, PAGE_BOOT_FETCH_DELAY_MS);
    queueConversationPreviews("matches-page-previews", {
      delayMs: PAGE_SECONDARY_FETCH_DELAY_MS,
    });

    return () => {
      bootStartedRef.current = false;
      cancelBootLoad();
      previewLoadCancelRef.current?.();
      previewLoadCancelRef.current = null;
    };
  }, [loadMatchRows, queueConversationPreviews]);

  useEffect(() => {
    const refetch = () => {
      void loadMatchRows("matches-sync", { background: true });
      queueConversationPreviews("matches-sync-previews", {
        delayMs: PAGE_BOOT_FETCH_DELAY_MS,
      });
    };
    const onMarkSeen = () => refetch();
    window.addEventListener(MATCHES_MARK_SEEN_EVENT, onMarkSeen);
    const onShow = (event: PageTransitionEvent) => {
      if (event.persisted) refetch();
    };
    window.addEventListener("pageshow", onShow);
    return () => {
      window.removeEventListener(MATCHES_MARK_SEEN_EVENT, onMarkSeen);
      window.removeEventListener("pageshow", onShow);
    };
  }, [loadMatchRows, queueConversationPreviews]);

  const previewByPartner = useMemo(() => {
    const map = new Map<number, ConvoRow>();
    convos.forEach((row) => map.set(row.partner_user_id, row));
    return map;
  }, [convos]);

  useEffect(() => {
    if (!matches.length) return;
    let cancelled = false;
    const candidates = matches
      .map((m) => Math.trunc(Number(m.partner_user_id)))
      .filter((id) => Number.isFinite(id) && id > 0)
      .slice(0, 12);

    // Only pre-generate for matches with no conversation preview (likely first message).
    const need = candidates.filter((pid) => {
      const convo = previewByPartner.get(pid);
      const hasPreview = Boolean(String(convo?.last_message_preview || "").trim());
      return !hasPreview && !openerByPartnerId.has(pid);
    });
    if (!need.length) return;

    void (async () => {
      for (const pid of need.slice(0, 6)) {
        try {
          const match = matches.find((m) => m.partner_user_id === pid) ?? null;
          if (!match) continue;
          const res = await getAiOpeners(
            `matches:${pid}`,
            { matchName: match.partner_display_name, city: match.partner_city || null },
            { aiCtx: { uiLocale: locale || "en" } },
          );
          if (cancelled) return;
          const variants = (res.items || []).map((x) => String(x?.text || "").trim()).filter(Boolean).slice(0, 3);
          const bestIndex = Math.max(0, Math.min(variants.length - 1, res.bestIndex ?? 0));
          if (variants.length) {
            setOpenerByPartnerId((prev) => {
              const next = new Map(prev);
              next.set(pid, { variants, bestIndex });
              return next;
            });
          }
        } catch {
          /* silent */
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [matches, openerByPartnerId, previewByPartner, locale]);

  useEffect(() => {
    if (!viewerProfileId) return;
    if (!matches.length) return;
    let cancelled = false;
    const candidateProfileIds = matches
      .map((match) => Math.trunc(Number(match.partner_user_id)))
      .filter((id) => Number.isFinite(id) && id > 0)
      .slice(0, 25);
    void fetchCompatibilityScoresBatch({ viewerProfileId, candidateProfileIds })
      .then((map) => {
        if (cancelled) return;
        setCompatByPartnerId(map);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [matches, viewerProfileId]);

  const matchesAiHiddenReason =
    !viewerProfileId
      ? "Matches AI preview hidden: viewer profile missing."
      : !matches.length
        ? "Matches AI preview hidden: no matches loaded."
        : compatByPartnerId.size
          ? null
          : "Matches AI preview hidden: no compatibility results yet.";

  useEffect(() => {
    logAiGate("matches-ui", {
      forceVisible: FORCE_AI_VISIBLE,
      matchCount: matches.length,
      viewerProfileId,
      compatibilityCount: compatByPartnerId.size,
      hiddenReason: matchesAiHiddenReason,
    });
  }, [compatByPartnerId, matches.length, matchesAiHiddenReason, viewerProfileId]);

  const status =
    !loading && matches.length > 0
      ? matches.length === 1
        ? t("matches.header.status.one", { count: matches.length })
        : t("matches.header.status.other", { count: matches.length })
      : undefined;

  const openChat = useCallback(
    (match: MatchRow, opts?: { ai?: boolean; focus?: boolean }) => {
      if (opts?.ai) queueNextPageToast(i18nKey("premium.moment.beforeFirstMessage"));
      else queueNextPageToast(i18nKey("premium.moment.afterMatch"));
      const partnerUserId = match.partner_user_id;
      const q = new URLSearchParams();
      if (opts?.ai) {
        q.set("match", "1");
        q.set("ai", "openers");
      }
      if (opts?.focus) q.set("focus", "1");
      const href = `/chat/${partnerUserId}${q.toString() ? `?${q.toString()}` : ""}`;
      debugChat("navigate thread from matches", {
        partnerUserId,
        matchId: match.match_id,
        ai: Boolean(opts?.ai),
        focus: Boolean(opts?.focus),
      });
      setChatThreadHeaderSeed(partnerUserId, {
        displayName: match.partner_display_name,
        avatarUrl: resolvePhoto(match),
      });
      router.push(href);
    },
    [router],
  );

  const activityBadge = (match: MatchRow, convo: ConvoRow | undefined): { label: string; tone: "default" | "premium" } | null => {
    const ts = String(convo?.last_message_at || match.matched_at || "").trim();
    if (!ts) return null;
    const ms = Date.parse(ts);
    if (!Number.isFinite(ms)) return null;
    const ageMin = Math.max(0, Math.round((Date.now() - ms) / 60000));
    if (ageMin <= 20) return { label: "•", tone: "premium" }; // subtle "online-ish" dot (no new i18n keys)
    if (ageMin <= 24 * 60) return { label: "•", tone: "default" };
    return null;
  };

  const likesTodayCount = Math.max(0, Math.min(99, likesIncomingStats?.today ?? 0));
  const likesWaitingCount = Math.max(0, Math.min(999, likesIncomingStats?.waiting ?? 0));
  const likesToday = Math.max(0, Math.min(999, likesIncomingStats?.today ?? likesIncomingStats?.waiting ?? 0));

  useEffect(() => {
    if (liveActivityLoggedRef.current) return;
    liveActivityLoggedRef.current = true;
    // Debug log once: helps confirm real API-derived likes count.
    console.log("matches_live_activity_likes_count", { likesToday });
  }, [likesToday]);

  return (
    <>
      <PageShell>
        <PageHeader
          title={t("matches.header.title")}
          subtitle={t("matches.header.subtitle")}
          status={status}
        />

        <section aria-label={t("matches.header.title")}>
          {(() => {
            const waitingMatches = matches.length;
            const trending = matches.length >= 3;
            const bannerLines: { key: string; node: ReactNode }[] = [];
            // ALWAYS render likes row (never hidden behind counts/loading/premium).
            const likesRowText = likesToday > 0 ? `🔥 ${likesToday} people liked you today` : "🔥 People liked you today";
            bannerLines.push({
              key: "likes",
              node: (
                <button
                  type="button"
                  data-testid="matches-live-likes"
                  className="live-activity-item"
                  aria-label={t("matches.banner.likesTodayAria")}
                  onClick={() => router.push("/likes")}
                >
                  {likesRowText}
                </button>
              ),
            });

            // ALWAYS render matches row (QA-critical).
            const matchesCount = Math.max(0, Math.trunc(matches.length || 0));
            bannerLines.push({
              key: "matches",
              node: (
                <button
                  type="button"
                  data-testid="matches-live-matches"
                  className="live-activity-item"
                  aria-label={t("matches.banner.matchesWaiting", { count: matchesCount })}
                  onClick={() => {
                    const first = matches[0];
                    if (!first) {
                      router.push("/chat");
                      return;
                    }
                    openChat(first, { focus: true });
                  }}
                >
                  💬 {matchesCount} match waiting
                </button>
              ),
            });
            if (trending) {
              bannerLines.push({ key: "trend", node: t("matches.banner.trending") });
            }
            return bannerLines.length ? (
              <Card className="surface surface--inset matches-live-banner" style={{ marginBottom: 12, padding: 14 }}>
                <div className="section-label">{t("matches.banner.title")}</div>
                <div className="caption matches-live-banner__lines" style={{ marginTop: 8, opacity: 0.92, display: "grid", gap: 6 }}>
                  {bannerLines.map((line) => (
                    <div key={line.key}>{line.node}</div>
                  ))}
                </div>
              </Card>
            ) : null;
          })()}

          {hasLikesPreview ? (
            <div className="matches-section-head">
              <div className="matches-section-head__title">{t("matches.sections.likesYou")}</div>
              <div className="caption matches-section-head__sub">
                {t("matches.likes.emotional")}
                <span style={{ opacity: 0.7 }}> · </span>
                {t("matches.likes.freeHook")}
              </div>
            </div>
          ) : null}

          <LikesYouPanel variant="embedded" limit={3} onHasRealLikes={setHasLikesPreview} />
          {(hasLikesPreview || likesTodayCount > 0 || likesWaitingCount > 0) ? (
            <div style={{ marginTop: 10, display: "flex", justifyContent: "flex-start" }}>
              <Link className="btn btn-secondary" href="/likes">
                {t("matches.likes.seeWhoCta")}
              </Link>
            </div>
          ) : null}

          <div className="matches-section-head" style={{ marginTop: 14 }}>
            <div className="matches-section-head__title">{t("matches.sections.yourMatches")}</div>
            <div className="caption matches-section-head__sub">{t("matches.sections.yourMatchesSubtitle")}</div>
          </div>

        {AI_DEBUG_ENABLED ? <AiDebugPill label={FORCE_AI_VISIBLE ? "FORCE_AI_VISIBLE active: matches AI preview is forced visible in dev." : matchesAiHiddenReason} style={{ marginBottom: 12 }} /> : null}

        {loadError && !loading ? (
          <Card className="surface" style={{ padding: 18 }}>
            <p className="body" style={{ margin: 0 }}>
              {resolveI18nText(loadError, t)}
            </p>
            <div style={{ marginTop: 14 }}>
              <Button
                type="button"
                variant="primary"
                onClick={() => {
                  void loadMatchRows("matches-manual-refresh", { forceFresh: true });
                  queueConversationPreviews("matches-manual-refresh-previews", {
                    forceFresh: true,
                    delayMs: PAGE_BOOT_FETCH_DELAY_MS,
                  });
                }}
              >
                {t("common.tryAgain")}
              </Button>
            </div>
          </Card>
        ) : null}

        {loading ? (
          <div className="matches-list">
            {[0, 1, 2, 3].map((index) => (
              <Card key={index} className="surface match-row match-row--skeleton">
                <div className="match-row__main">
                  <Skeleton style={{ width: 56, height: 56, borderRadius: 18, flexShrink: 0 }} />
                  <div className="match-row__text" style={{ flex: 1, minWidth: 0 }}>
                    <Skeleton style={{ height: 16, width: "48%", borderRadius: 8 }} />
                    <div style={{ height: 8 }} />
                    <Skeleton style={{ height: 13, width: "72%", borderRadius: 8 }} />
                    <div style={{ height: 8 }} />
                    <Skeleton style={{ height: 12, width: "90%", borderRadius: 8 }} />
                  </div>
                </div>
                <div className="match-row__actions">
                  <Skeleton style={{ height: 44, flex: 1, borderRadius: 999, minWidth: 120 }} />
                  <Skeleton style={{ height: 44, flex: 1, borderRadius: 999, minWidth: 100 }} />
                </div>
              </Card>
            ))}
          </div>
        ) : !loadError && matches.length === 0 ? (
          <Card className="surface">
            <EmptyState
              kicker="♥"
              title={t("matches.empty.title")}
              description={t("matches.empty.description")}
              spacious
            >
              <Link className="btn btn-primary" href="/discover">
                {t("matches.empty.discover")}
              </Link>
              <Link className="btn btn-ghost" href="/profile">
                {t("matches.empty.profile")}
              </Link>
            </EmptyState>
          </Card>
        ) : loadError ? null : (
          <div className="matches-list">
            {(() => {
              const inactiveCutoffMs = 2 * 24 * 60 * 60 * 1000;
              const isInactive = (match: MatchRow): boolean => {
                const convo = previewByPartner.get(match.partner_user_id);
                const ts = String(convo?.last_message_at || "").trim();
                if (!ts) return false;
                const ms = Date.parse(ts);
                if (!Number.isFinite(ms)) return false;
                return Date.now() - ms >= inactiveCutoffMs;
              };

              const inactive = matches.filter(isInactive);
              const active = matches.filter((m) => !isInactive(m));

              const renderMatchCard = (match: MatchRow, opts?: { inactive?: boolean }) => {
              const convo = previewByPartner.get(match.partner_user_id);
              const compat = compatByPartnerId.get(match.partner_user_id) ?? null;
              const preview = convo?.last_message_preview?.trim() || t("matches.previewFallback");
              const when = convo?.last_message_at
                ? new Date(convo.last_message_at).toLocaleDateString(locale, { month: "short", day: "numeric" })
                : null;
              const unread = convo?.unread_count ?? 0;
              const hasThreadActivity = Boolean(convo?.last_message_at?.trim());
              const inboxSaysFullyRead = hasThreadActivity && unread === 0;
              const isNew =
                Boolean(match.is_new_match) &&
                !isMatchesNewBadgeDismissedForPartner(match.partner_user_id) &&
                !inboxSaysFullyRead;
              const ageLine = match.partner_age != null && match.partner_age > 0 ? `${match.partner_age}` : null;
              const city = String((match as any)?.partner_city ?? "").trim();
              const metaBits = [ageLine, city || null].filter(Boolean).join(" · ");
              const act = activityBadge(match, convo);
              const partnerName = String((match as any)?.partner_display_name ?? "").trim() || t("common.someone");
              const partnerPhoto = resolveMediaUrl(String(resolvePhoto(match) || "").trim());
              const inactiveLabel = opts?.inactive ? t("matches.inactive.label") : "";
              const hasConversation = Boolean(String(convo?.last_message_preview || "").trim());
              const openerPack = openerByPartnerId.get(match.partner_user_id) ?? null;
              const suggestedList = !hasConversation && openerPack ? openerPack.variants.filter(Boolean).slice(0, 3) : [];
              const sending = Boolean(sendingByPartnerId.get(match.partner_user_id));

              return (
                <article
                  key={match.match_id}
                  className={`match-row surface ${isNew ? "match-row--new" : ""} ${act ? "match-row--active" : ""} ${match.partner_verified ? "trust-verified" : ""} ${match.partner_is_premium ? "match-row--premium" : ""}`.trim()}
                  role="button"
                  tabIndex={0}
                  onClick={() => openChat(match, { focus: true })}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      openChat(match, { focus: true });
                    }
                  }}
                >
                  <div className="match-row__main">
                    <SafeImg
                      className="match-row__avatar"
                      src={partnerPhoto}
                      alt=""
                      loading="lazy"
                      photoTestId="match-avatar-img"
                    />
                    <div className="match-row__text">
                      <div className="match-row__title-line">
                        <span className="match-row__name">
                          <Link href={`/people/${match.partner_user_id}`} prefetch={false} onClick={(e) => e.stopPropagation()}>
                            {partnerName}
                          </Link>
                          {match.partner_verified ? <VerifiedBadge title={t("trust.verified.tooltip")} /> : null}
                          {match.partner_is_premium ? <PremiumBadge title={t("premium.badge")} /> : null}
                        </span>
                        {act ? <Badge tone={act.tone}>{act.label}</Badge> : null}
                        {inactiveLabel ? <Badge>{inactiveLabel}</Badge> : null}
                        {isNew ? (
                          <span className="match-row__new-pill" aria-label={t("matches.new")}>
                            {t("matches.new")}
                          </span>
                        ) : null}
                      </div>
                      {metaBits ? <div className="match-row__meta">{metaBits}</div> : null}
                      {compat?.available && typeof compat.score === "number" && compat.score > 0 ? (
                        <div className="match-row__ai-line">
                          <Badge tone="premium">{t("matches.aiCompatPercent", { score: compat.score })}</Badge>
                          {(() => {
                            const line = renderDiscoverReason(compat.reasons?.[0] ?? "", t);
                            return line ? <span className="match-row__ai-reason">💡 {line}</span> : null;
                          })()}
                        </div>
                      ) : null}
                      <p className="match-row__preview">{preview}</p>
                      {when ? <div className="match-row__time">{t("matches.lastMessage", { date: when })}</div> : null}
                    </div>
                  </div>
                  <div className="match-row__actions">
                    {!hasConversation && suggestedList.length ? (
                      <div className="match-row__oneTap">
                        <div className="match-row__oneTap-label">💬 {t("matches.oneTap.waiting")}</div>
                        <div className="match-row__oneTap-list" role="list">
                          {suggestedList.map((txt, idx) => (
                            <button
                              key={idx}
                              type="button"
                              className="match-row__oneTap-chip"
                              disabled={sending}
                              onClick={(e) => {
                                e.stopPropagation();
                                // 1 tap = insert draft in chat; 2nd tap = Send (in chat quick bar).
                                const pid = match.partner_user_id;
                                const content = String(txt || "").trim();
                                if (!content) return;
                                setChatThreadHeaderSeed(pid, {
                                  displayName: match.partner_display_name,
                                  avatarUrl: resolvePhoto(match),
                                });
                                const q = new URLSearchParams({ focus: "1", draft: content, quick_send: "1" });
                                router.push(`/chat/${pid}?${q.toString()}`);
                              }}
                            >
                              “{txt}”
                            </button>
                          ))}
                        </div>
                        <div className="match-row__oneTap-actions">
                          <button
                            type="button"
                            className="btn btn-secondary match-row__btn-profile"
                            disabled={sending}
                            onClick={(e) => {
                              e.stopPropagation();
                              openChat(match, { ai: true });
                            }}
                          >
                            {t("matches.oneTap.otherOptions")}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <Link
                          className="btn btn-primary match-row__btn-chat"
                          href={`/chat/${match.partner_user_id}?focus=1`}
                          prefetch={false}
                          onClick={(e) => {
                            e.stopPropagation();
                            openChat(match, { focus: true });
                          }}
                        >
                          💬 {t("matches.cta.sayHi")}
                        </Link>
                        <Link
                          className="btn btn-ghost match-row__btn-profile"
                          href={`/chat/${match.partner_user_id}?match=1&ai=openers`}
                          prefetch={false}
                          onClick={(e) => {
                            e.stopPropagation();
                            openChat(match, { ai: true });
                          }}
                        >
                          ✨ {opts?.inactive ? t("matches.cta.reviveWithAi") : t("matches.cta.generateOpener")}
                        </Link>
                      </>
                    )}
                  </div>
                </article>
              );
              };

              return (
                <>
                  {active.map((m) => renderMatchCard(m))}
                  {inactive.length ? (
                    <>
                      <div className="matches-section-head" style={{ marginTop: 14 }}>
                        <div className="matches-section-head__title">{t("matches.sections.inactive")}</div>
                        <div className="caption matches-section-head__sub">{t("matches.sections.inactiveSubtitle")}</div>
                      </div>
                      {inactive.map((m) => renderMatchCard(m, { inactive: true }))}
                    </>
                  ) : null}
                </>
              );
            })()}
          </div>
        )}
        </section>
      </PageShell>
      <Toast text={resolveI18nText(toast, t)} onClose={() => setToast(null)} />
    </>
  );
}
