"use client";

/**
 * Single chat surface for meeting escalation (no duplicate banners elsewhere):
 * - Full card when backend returns meeting_options + ready stage + score rules.
 * - Moment strip when show_moment_hint (backend) and not showing the full card.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage } from "../../../lib/chat/types";
import type { ConversationState } from "../../../lib/chat/aiLanguageTone";
import { trackAnalyticsEvent } from "../../../lib/analytics";
import { useT } from "../i18n/I18nProvider";
import { fetchMeetingReadiness, type MeetingOption } from "../../../lib/chat/api";

/** Enough history for closer scoring / hint path */
const MIN_MESSAGES_EVAL = 8;
/** Full meeting card still requires substantive thread */
const MIN_MESSAGES_CARD = 15;
const MOMENT_HINT_MIN_SCORE = 65;
const SNOOZE_MS = 7 * 24 * 60 * 60 * 1000;

function snoozeKey(partnerId: number) {
  return `neyra:meeting_suggest_snooze:${partnerId}`;
}

function getSnoozeUntil(partnerId: number): number {
  try {
    const v = Number(localStorage.getItem(snoozeKey(partnerId)) || "");
    return Number.isFinite(v) ? v : 0;
  } catch {
    return 0;
  }
}

function snooze(partnerId: number) {
  try {
    localStorage.setItem(snoozeKey(partnerId), String(Date.now() + SNOOZE_MS));
  } catch {
    /* ignore */
  }
}

export type MeetingSuggestKind = "coffee" | "walk" | "drinks" | "custom";

type Props = {
  partnerUserId: number | null;
  viewerUserId: number | null;
  userCity?: string | null;
  messages: ChatMessage[];
  conversationState: ConversationState;
  composerDraft?: string;
  disabled?: boolean;
  onInsert: (text: string, meta: { kind: MeetingSuggestKind }) => void;
};

export function meetingSuggestEligible(
  messages: ChatMessage[],
  conversationState: ConversationState,
  partnerUserId: number | null,
  viewerUserId: number | null,
): boolean {
  if (partnerUserId == null || viewerUserId == null) return false;
  if (conversationState !== "active") return false;
  return (messages?.length ?? 0) >= MIN_MESSAGES_EVAL;
}

export function ChatMeetingSuggestInline({
  partnerUserId,
  viewerUserId,
  userCity = null,
  messages,
  conversationState,
  composerDraft = "",
  disabled = false,
  onInsert,
}: Props) {
  const { t } = useT("ChatMeetingSuggestInline");
  const [dismissed, setDismissed] = useState(false);
  const [momentDismissed, setMomentDismissed] = useState(false);
  const shownRef = useRef(false);
  const momentShownRef = useRef(false);
  const lastEvalKeyRef = useRef<string>("");
  const [gate, setGate] = useState<{
    ok: boolean;
    score: number | null;
    stage: string | null;
    options: MeetingOption[];
    showMoment: boolean;
    closerSuggestions: string[];
    closerStage: string | null;
  }>({
    ok: false,
    score: null,
    stage: null,
    options: [],
    showMoment: false,
    closerSuggestions: [],
    closerStage: null,
  });

  const eligible = useMemo(
    () => meetingSuggestEligible(messages, conversationState, partnerUserId, viewerUserId),
    [conversationState, messages, partnerUserId, viewerUserId],
  );

  const draftBusy = Boolean(String(composerDraft || "").trim());
  const snoozeUntil = partnerUserId != null ? getSnoozeUntil(partnerUserId) : 0;
  const pastSnooze = Date.now() >= snoozeUntil;

  const shouldEvaluate = Boolean(eligible && !disabled && pastSnooze && partnerUserId != null && viewerUserId != null);

  const messageCount = messages?.length ?? 0;
  const fullCardMessageOk = messageCount >= MIN_MESSAGES_CARD;

  const shouldShowFull =
    Boolean(eligible && !disabled && !draftBusy && !dismissed && pastSnooze && partnerUserId != null && gate.ok);

  const shouldShowMoment = Boolean(
    eligible &&
      !disabled &&
      !draftBusy &&
      !momentDismissed &&
      pastSnooze &&
      partnerUserId != null &&
      gate.showMoment &&
      !gate.ok &&
      gate.closerSuggestions.length >= 3,
  );

  useEffect(() => {
    shownRef.current = false;
    momentShownRef.current = false;
  }, [partnerUserId]);

  useEffect(() => {
    if (!shouldEvaluate) return;
    const recent = (messages || []).slice(-40);
    const key = `${partnerUserId}:${recent.length}:${String((recent[recent.length - 1] as any)?.rawId ?? (recent[recent.length - 1] as any)?.id ?? (recent[recent.length - 1] as any)?.createdAt ?? "")}`;
    if (lastEvalKeyRef.current === key) return;
    lastEvalKeyRef.current = key;

    const rows = recent
      .map((m) => {
        const sender = Number((m as any)?.senderId);
        const role = sender === Number(viewerUserId) ? "me" : sender === Number(partnerUserId) ? "them" : null;
        const text = String((m as any)?.content || "").trim();
        const tsRaw = String((m as any)?.timestamp ?? (m as any)?.createdAt ?? "").trim();
        const ms = tsRaw ? Date.parse(tsRaw) : NaN;
        return role && text ? { role, text, ts_ms: Number.isFinite(ms) ? ms : null } : null;
      })
      .filter(Boolean) as { role: "me" | "them"; text: string; ts_ms: number | null }[];

    if (rows.length < MIN_MESSAGES_EVAL) {
      setGate({
        ok: false,
        score: null,
        stage: null,
        options: [],
        showMoment: false,
        closerSuggestions: [],
        closerStage: null,
      });
      return;
    }

    void (async () => {
      try {
        const readiness = await fetchMeetingReadiness({
          partnerUserId,
          city: userCity,
          messages: rows,
        });
        const scoreRaw = readiness?.readiness_score ?? readiness?.score ?? null;
        const score = scoreRaw != null ? Math.max(0, Math.min(100, Math.trunc(Number(scoreRaw)))) : null;
        const stage = readiness?.stage ?? null;
        const opts = readiness?.meeting_options ?? [];
        const closerSuggestions = readiness?.closer_suggestions ?? [];
        const closerStage = readiness?.closer_stage ? String(readiness.closer_stage) : null;
        const hintFlag = Boolean(readiness?.show_moment_hint);
        const ok = Boolean(
          fullCardMessageOk &&
            stage === "ready" &&
            score != null &&
            score >= 75 &&
            opts.length >= 3,
        );
        const showMoment = Boolean(
          hintFlag &&
            score != null &&
            score >= MOMENT_HINT_MIN_SCORE &&
            closerSuggestions.length >= 3 &&
            !ok,
        );
        setGate({
          ok,
          score,
          stage: stage ? String(stage) : null,
          options: opts,
          showMoment,
          closerSuggestions,
          closerStage,
        });
      } catch {
        setGate({
          ok: false,
          score: null,
          stage: null,
          options: [],
          showMoment: false,
          closerSuggestions: [],
          closerStage: null,
        });
      }
    })();
  }, [messages, partnerUserId, shouldEvaluate, viewerUserId, userCity, fullCardMessageOk]);

  useEffect(() => {
    if (!shouldShowFull || partnerUserId == null) return;
    if (shownRef.current) return;
    shownRef.current = true;
    void trackAnalyticsEvent("meeting_card_shown", { partner_user_id: partnerUserId, score: gate.score, stage: gate.stage });
    void fetchMeetingReadiness({ partnerUserId, city: userCity, messages: [], markShown: true }).catch(() => {});
  }, [partnerUserId, shouldShowFull]);

  useEffect(() => {
    if (!shouldShowMoment || partnerUserId == null) return;
    if (momentShownRef.current) return;
    momentShownRef.current = true;
    void trackAnalyticsEvent("meeting_suggested", {
      partner_user_id: partnerUserId,
      score: gate.score,
      closer_stage: gate.closerStage,
      variant: "moment_hint",
    });
  }, [partnerUserId, shouldShowMoment, gate.score, gate.closerStage]);

  if (shouldShowFull) {
    const baseSuggestions: { kind: MeetingSuggestKind; line: string; label: string }[] = [
      { kind: "coffee", label: t("chat.meetingSuggest.kind.coffee"), line: gate.options.find((o) => o.kind === "coffee")?.text || "" },
      { kind: "walk", label: t("chat.meetingSuggest.kind.walk"), line: gate.options.find((o) => o.kind === "walk")?.text || "" },
      { kind: "drinks", label: t("chat.meetingSuggest.kind.drinks"), line: gate.options.find((o) => o.kind === "drinks")?.text || "" },
      { kind: "custom", label: t("chat.meetingSuggest.kind.custom"), line: t("chat.meetingSuggest.customHint") },
    ];
    const suggestions = baseSuggestions.filter((s) => s.kind === "custom" || Boolean(s.line.trim()));

    return (
      <div className="chat-first-opener chat-first-opener--in" aria-label={t("chat.meetingSuggest.aria")}>
        <div className="chat-first-opener__badge">{t("chat.meetingSuggest.title")}</div>
        <div className="caption" style={{ marginTop: 6, opacity: 0.88, lineHeight: 1.35 }}>
          {t("chat.meetingSuggest.subtitle")}
        </div>
        <div className="chat-first-opener__options" role="list" style={{ marginTop: 10 }}>
          {suggestions.map((s) => (
            <button
              key={s.kind}
              type="button"
              className="chat-first-opener__option chat-first-opener__option--selected"
              disabled={disabled}
              onClick={() => {
                void trackAnalyticsEvent("meeting_option_clicked", {
                  partner_user_id: partnerUserId,
                  kind: s.kind,
                });
                void trackAnalyticsEvent("meeting_clicked", {
                  partner_user_id: partnerUserId,
                  kind: s.kind,
                  surface: "full_card",
                });
                void trackAnalyticsEvent("ai_suggestion_used", {
                  partner_user_id: partnerUserId,
                  source: "meeting_full_card",
                  kind: s.kind,
                });
                snooze(partnerUserId);
                onInsert(s.line, { kind: s.kind });
              }}
            >
              <div className="chat-first-opener__option-type">{s.label}</div>
              <div className="chat-first-opener__option-text">{s.line}</div>
            </button>
          ))}
        </div>
        <div style={{ marginTop: 10 }}>
          <button
            type="button"
            className="btn btn-ghost"
            style={{ fontSize: "0.9rem", opacity: 0.85 }}
            disabled={disabled}
            onClick={() => {
              void trackAnalyticsEvent("meeting_declined", { partner_user_id: partnerUserId });
              snooze(partnerUserId);
              setDismissed(true);
            }}
          >
            {t("chat.meetingSuggest.dismiss")}
          </button>
        </div>
      </div>
    );
  }

  if (shouldShowMoment) {
    return (
      <div
        className="chat-first-opener chat-first-opener--in"
        aria-label={t("chat.meetingMomentHint.aria")}
        style={{ borderColor: "rgba(124, 92, 255, 0.22)" }}
      >
        <div className="chat-first-opener__badge" style={{ fontWeight: 600, opacity: 0.95 }}>
          {t("chat.meetingMomentHint.title")}
        </div>
        <div className="caption" style={{ marginTop: 6, opacity: 0.85, lineHeight: 1.35 }}>
          {t("chat.meetingMomentHint.subtitle")}
        </div>
        <div className="chat-first-opener__options" role="list" style={{ marginTop: 10 }}>
          {gate.closerSuggestions.slice(0, 3).map((line, idx) => (
            <button
              key={`${idx}:${line.slice(0, 24)}`}
              type="button"
              className="chat-first-opener__option"
              disabled={disabled}
              onClick={() => {
                void trackAnalyticsEvent("ai_suggestion_used", {
                  partner_user_id: partnerUserId,
                  source: "closer_inline",
                  index: idx,
                  closer_stage: gate.closerStage,
                });
                void trackAnalyticsEvent("meeting_clicked", {
                  partner_user_id: partnerUserId,
                  surface: "moment_hint",
                  index: idx,
                });
                onInsert(line, { kind: "custom" });
              }}
            >
              <div className="chat-first-opener__option-text">{line}</div>
            </button>
          ))}
        </div>
        <div style={{ marginTop: 10 }}>
          <button
            type="button"
            className="btn btn-ghost"
            style={{ fontSize: "0.9rem", opacity: 0.85 }}
            disabled={disabled}
            onClick={() => setMomentDismissed(true)}
          >
            {t("chat.meetingMomentHint.dismiss")}
          </button>
        </div>
      </div>
    );
  }

  return null;
}
