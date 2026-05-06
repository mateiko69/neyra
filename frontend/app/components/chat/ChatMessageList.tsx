"use client";

import type { ReactNode } from "react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { CHAT_REACTION_EMOJIS, type ChatMessage, type ChatReactionEmoji } from "../../../lib/chat/types";
import { useT } from "../i18n/I18nProvider";
import { inspectI18nText, renderDebugText } from "../i18n/debugText";
import { Skeleton } from "../ui";
import { ChatAvatar } from "./ChatAvatar";

type ChatMessageListProps = {
  /** When true and there are no messages yet, show the thread skeleton (initial load only). */
  showLoadingSkeleton: boolean;
  /** Simulated “partner is typing” (e.g. delayed demo reply). */
  showPartnerTyping?: boolean;
  /** Optional override for typing aria label (e.g. demo profile typing). */
  partnerTypingAriaLabel?: string | null;
  messages: ChatMessage[];
  reactionPendingByMessageId?: Record<string, ChatReactionEmoji>;
  currentUserId: number | null;
  partnerUserId: number;
  partnerName: string;
  partnerAvatarUrl: string | null;
  myName: string;
  myAvatarUrl: string | null;
  /** Large empty UI (e.g. load error). When null and there are no messages, the list area stays compact. */
  emptyState: ReactNode | null;
  onRetryMessage?: (clientTempId: string) => void;
  onRetryVoiceMessage?: (clientTempId: string) => void;
  onReplyMessage?: (message: ChatMessage) => void;
  onReactMessage?: (messageId: number, emoji: ChatReactionEmoji) => void;
  /** Rendered directly under the last partner text message (e.g. auto AI reply chips). */
  inlineUnderLastPartnerMessage?: ReactNode;
  /** Load previous page of messages (server pagination). */
  hasMoreOlder?: boolean;
  olderLoading?: boolean;
  onLoadOlder?: () => void;
  /** Brief glow on this message id (e.g. new partner reply). */
  partnerReplyGlowId?: string | null;
  /** Optional non-overlay content rendered in the same scroll flow below messages. */
  afterMessagesContent?: ReactNode;
  /** Thread-level actions surfaced via per-message menu. */
  canDeleteThread?: boolean;
  partnerIgnored?: boolean;
  onDeleteThread?: () => void;
  onIgnorePartner?: () => void;
  onUnignorePartner?: () => void;
};

function dayKey(value: string | null): string {
  if (!value) return "undated";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "undated";
  return date.toISOString().slice(0, 10);
}

function formatDayLabel(value: string | null, locale: string, fallback: string): string {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  const now = new Date();
  const isSameYear = now.getFullYear() === date.getFullYear();
  return date.toLocaleDateString(
    locale,
    isSameYear ? { month: "long", day: "numeric" } : { year: "numeric", month: "long", day: "numeric" },
  );
}

function formatMessageTime(value: string | null, locale: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
}

function formatDurationMs(durationMs: number | null | undefined): string | null {
  if (durationMs == null || !Number.isFinite(durationMs)) return null;
  const totalSeconds = Math.max(0, Math.round(durationMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function isOwnMessage(message: ChatMessage, currentUserId: number | null, partnerUserId: number): boolean {
  if (currentUserId != null) return message.senderId === currentUserId;
  return message.senderId !== partnerUserId;
}

function shouldRenderMessage(message: ChatMessage, currentUserId: number | null, partnerUserId: number): boolean {
  const role = String((message as any).role || "").trim().toLowerCase();
  if (role === "assistant" || role === "system") return false;
  // Enforce: only viewer + partner messages are allowed in the thread UI.
  const sender = Number(message.senderId);
  const partner = Number(partnerUserId);
  if (Number.isFinite(partner) && sender === partner) return true;
  if (currentUserId != null && sender === Number(currentUserId)) return true;
  return false;
}

function isNearBottom(element: HTMLDivElement): boolean {
  return element.scrollHeight - element.scrollTop - element.clientHeight < 140;
}

function resolveScrollHost(scroller: HTMLDivElement | null): HTMLDivElement | null {
  if (!scroller) return null;
  return scroller;
}

function groupKeyForMessage(message: ChatMessage): string {
  return `${message.senderId}:${dayKey(message.timestamp)}`;
}

function reactionSortIndex(emoji: string): number {
  const index = CHAT_REACTION_EMOJIS.indexOf(emoji as ChatReactionEmoji);
  return index === -1 ? Number.MAX_SAFE_INTEGER : index;
}

export function ChatMessageList({
  showLoadingSkeleton,
  showPartnerTyping = false,
  partnerTypingAriaLabel = null,
  messages,
  reactionPendingByMessageId,
  currentUserId,
  partnerUserId,
  partnerName,
  partnerAvatarUrl,
  myName,
  myAvatarUrl,
  emptyState,
  onRetryMessage,
  onRetryVoiceMessage,
  onReplyMessage,
  onReactMessage,
  inlineUnderLastPartnerMessage = null,
  hasMoreOlder = false,
  olderLoading = false,
  onLoadOlder,
  partnerReplyGlowId = null,
  afterMessagesContent = null,
  canDeleteThread = false,
  partnerIgnored = false,
  onDeleteThread,
  onIgnorePartner,
  onUnignorePartner,
}: ChatMessageListProps) {
  const { t, locale } = useT("ChatMessageList");
  const visibleMessages = useMemo(() => {
    return (messages || []).filter((m) => shouldRenderMessage(m, currentUserId, partnerUserId));
  }, [messages, currentUserId, partnerUserId]);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const bottomAnchorRef = useRef<HTMLDivElement | null>(null);
  const previousMessageCountRef = useRef(0);
  const [showNewMessages, setShowNewMessages] = useState(false);
  const [newMessageCount, setNewMessageCount] = useState(0);
  const [openReactionPickerId, setOpenReactionPickerId] = useState<string | null>(null);
  const [openActionsMenuId, setOpenActionsMenuId] = useState<string | null>(null);
  const atBottomRef = useRef(true);
  const seenMessageIdsRef = useRef<Set<string>>(new Set());
  const initialAutoScrollDoneRef = useRef(false);
  const initialAutoScrollThreadKeyRef = useRef<string>("");
  const initialAutoScrollRafRef = useRef<number | null>(null);
  const lastAutoScrolledMessageIdRef = useRef<string | null>(null);
  const outgoingAutoScrollDoneForIdRef = useRef<string | null>(null);
  const historyAria = inspectI18nText(t("chat.list.historyAria"), { component: "ChatMessageList", prop: "historyAria" });

  // Single audio player for the whole thread (only one plays at a time).
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const activeVoiceMessageIdRef = useRef<string | null>(null);
  const positionByMessageIdRef = useRef<Map<string, number>>(new Map());
  const durationProbeInFlightRef = useRef<Set<string>>(new Set());
  const [activeVoiceMessageId, setActiveVoiceMessageId] = useState<string | null>(null);
  const [voicePlaying, setVoicePlaying] = useState(false);
  const [voiceProgress, setVoiceProgress] = useState(0);
  const [durationByMessageId, setDurationByMessageId] = useState<Record<string, number>>({});

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (audioRef.current) return;
    const audio = new Audio();
    audio.preload = "metadata";
    audioRef.current = audio;

    const onTimeUpdate = () => {
      const id = activeVoiceMessageIdRef.current;
      if (!id) return;
      positionByMessageIdRef.current.set(id, audio.currentTime);
      const dur = Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : 0;
      setVoiceProgress(dur > 0 ? Math.min(1, Math.max(0, audio.currentTime / dur)) : 0);
    };
    const onEnded = () => {
      const id = activeVoiceMessageIdRef.current;
      if (id) positionByMessageIdRef.current.set(id, 0);
      setVoicePlaying(false);
      setVoiceProgress(0);
    };
    const onPause = () => setVoicePlaying(false);
    const onPlay = () => setVoicePlaying(true);
    const onLoadedMetadata = () => {
      const id = activeVoiceMessageIdRef.current;
      if (!id) return;
      if (Number.isFinite(audio.duration) && audio.duration > 0) {
        setDurationByMessageId((prev) => ({ ...prev, [id]: audio.duration }));
      }
    };

    audio.addEventListener("timeupdate", onTimeUpdate);
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("loadedmetadata", onLoadedMetadata);
    return () => {
      audio.removeEventListener("timeupdate", onTimeUpdate);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("loadedmetadata", onLoadedMetadata);
      audio.pause();
    };
  }, []);

  useEffect(() => {
    if (showLoadingSkeleton) return;
    // Cache durations for messages that don't have voiceDurationMs.
    const missing = visibleMessages.filter(
      (m) =>
        m.voiceUrl &&
        (m.voiceDurationMs == null || m.voiceDurationMs <= 0) &&
        !durationByMessageId[m.id] &&
        !durationProbeInFlightRef.current.has(m.id),
    );
    if (missing.length === 0) return;
    let cancelled = false;
    for (const msg of missing.slice(0, 8)) {
      durationProbeInFlightRef.current.add(msg.id);
      const a = new Audio();
      a.preload = "metadata";
      a.src = msg.voiceUrl!;
      a.addEventListener(
        "loadedmetadata",
        () => {
          durationProbeInFlightRef.current.delete(msg.id);
          if (cancelled) return;
          if (Number.isFinite(a.duration) && a.duration > 0) {
            setDurationByMessageId((prev) => ({ ...prev, [msg.id]: a.duration }));
          }
        },
        { once: true },
      );
      a.addEventListener(
        "error",
        () => {
          durationProbeInFlightRef.current.delete(msg.id);
        },
        { once: true },
      );
    }
    return () => {
      cancelled = true;
    };
  }, [showLoadingSkeleton, visibleMessages, durationByMessageId]);

  const rendered = useMemo(() => {
    return visibleMessages.map((message, index) => {
      const prev = index > 0 ? visibleMessages[index - 1] : null;
      const next = index < visibleMessages.length - 1 ? visibleMessages[index + 1] : null;

      const ownMessage = isOwnMessage(message, currentUserId, partnerUserId);
      const prevKey = prev ? groupKeyForMessage(prev) : null;
      const nextKey = next ? groupKeyForMessage(next) : null;
      const key = groupKeyForMessage(message);

      const groupStart = prevKey !== key;
      const groupEnd = nextKey !== key;
      const showDayMarker = !prev || dayKey(prev.timestamp) !== dayKey(message.timestamp);
      const isNew = !seenMessageIdsRef.current.has(message.id);

      return { message, ownMessage, groupStart, groupEnd, showDayMarker, isNew };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- derived UI snapshot, computed from messages only
  }, [visibleMessages, currentUserId, partnerUserId]);

  useLayoutEffect(() => {
    // Partner/thread change can arrive without a remount in some cases (e.g. dev tools/fast refresh).
    // Reset all scroll bookkeeping so the next successful render lands at the bottom.
    const threadKey = String(partnerUserId);
    if (initialAutoScrollThreadKeyRef.current !== threadKey) {
      initialAutoScrollThreadKeyRef.current = threadKey;
      initialAutoScrollDoneRef.current = false;
      previousMessageCountRef.current = 0;
      atBottomRef.current = true;
      setShowNewMessages(false);
      setNewMessageCount(0);
      lastAutoScrolledMessageIdRef.current = null;
      if (initialAutoScrollRafRef.current != null) {
        cancelAnimationFrame(initialAutoScrollRafRef.current);
        initialAutoScrollRafRef.current = null;
      }
    }
  }, [partnerUserId]);

  const messageById = useMemo(() => {
    const map = new Map<string, ChatMessage>();
    for (const message of visibleMessages) map.set(message.id, message);
    return map;
  }, [visibleMessages]);

  useEffect(() => {
    const audio = audioRef.current;
    const activeId = activeVoiceMessageIdRef.current;
    if (!audio || !activeId) return;

    const activeMessage = messageById.get(activeId) ?? messages.find((message) => message.clientTempId === activeId) ?? null;
    if (!activeMessage) {
      audio.pause();
      activeVoiceMessageIdRef.current = null;
      setActiveVoiceMessageId(null);
      setVoicePlaying(false);
      setVoiceProgress(0);
      return;
    }

    if (activeMessage.id !== activeId) {
      const previousPosition = positionByMessageIdRef.current.get(activeId);
      if (previousPosition != null) {
        positionByMessageIdRef.current.set(activeMessage.id, previousPosition);
      }
      activeVoiceMessageIdRef.current = activeMessage.id;
      setActiveVoiceMessageId(activeMessage.id);
    }

    const nextUrl = activeMessage.voiceUrl?.trim() || "";
    if (!nextUrl) return;

    const currentSrc = (audio.currentSrc || audio.src || "").trim();
    if (currentSrc === nextUrl) return;

    const resumeAt = Number.isFinite(audio.currentTime) ? audio.currentTime : positionByMessageIdRef.current.get(activeMessage.id) ?? 0;
    const shouldResume = !audio.paused;
    audio.pause();
    audio.src = nextUrl;

    const resumePlayback = () => {
      if (resumeAt > 0) {
        try {
          audio.currentTime = resumeAt;
        } catch {
          // Ignore seek failures on freshly swapped sources.
        }
      }
      positionByMessageIdRef.current.set(activeMessage.id, resumeAt);
      if (shouldResume) void audio.play().catch(() => {});
    };

    if (audio.readyState >= 1) resumePlayback();
    else audio.addEventListener("loadedmetadata", resumePlayback, { once: true });
  }, [messageById, messages]);

  useLayoutEffect(() => {
    const scroller = resolveScrollHost(scrollerRef.current);
    const anchor = bottomAnchorRef.current;
    if (!scroller || !anchor || showLoadingSkeleton) return;

    const nextCount = messages.length;
    const previousCount = previousMessageCountRef.current;
    const grew = nextCount > previousCount;
    const nearBottom = isNearBottom(scroller);
    atBottomRef.current = nearBottom;
    const shouldPin = nearBottom;

    previousMessageCountRef.current = nextCount;

    // Initial open: after the first successful render of the thread (post-skeleton), jump to bottom.
    // We "settle" for a few frames to avoid races with delayed header/profile rendering affecting layout.
    if (!initialAutoScrollDoneRef.current) {
      let attempts = 0;
      const settle = () => {
        const liveScroller = resolveScrollHost(scrollerRef.current);
        const liveAnchor = bottomAnchorRef.current;
        if (!liveScroller || !liveAnchor) return;
        liveAnchor.scrollIntoView({ block: "end", behavior: "auto" });
        atBottomRef.current = true;
        attempts += 1;
        if (attempts < 6) {
          initialAutoScrollRafRef.current = requestAnimationFrame(settle);
        } else {
          initialAutoScrollRafRef.current = null;
          initialAutoScrollDoneRef.current = true;
        }
      };
      if (initialAutoScrollRafRef.current == null) {
        initialAutoScrollRafRef.current = requestAnimationFrame(settle);
      }
      return;
    }

    // Subsequent growth: auto-scroll only once per newly added outgoing message.
    if (nextCount === 0 || !grew || !shouldPin) return;
    const lastMessageId = messages[messages.length - 1]?.id ?? null;
    if (lastMessageId && lastAutoScrolledMessageIdRef.current === lastMessageId) return;
    const lastMessage = messages[messages.length - 1] ?? null;
    if (!lastMessage || !isOwnMessage(lastMessage, currentUserId, partnerUserId)) return;
    if (outgoingAutoScrollDoneForIdRef.current === lastMessage.id) return;
    outgoingAutoScrollDoneForIdRef.current = lastMessage.id;
    lastAutoScrolledMessageIdRef.current = lastMessageId;
    console.warn("chat autoscroll triggered", { messageId: lastMessage.id });
    requestAnimationFrame(() => {
      bottomAnchorRef.current?.scrollIntoView({ block: "end", behavior: "auto" });
    });
  }, [showLoadingSkeleton, messages, currentUserId, partnerUserId]);

  useLayoutEffect(() => {
    if (showLoadingSkeleton) return;
    const scroller = resolveScrollHost(scrollerRef.current);
    if (!scroller) return;

    const onScroll = () => {
      const nearBottom = isNearBottom(scroller);
      atBottomRef.current = nearBottom;
      if (nearBottom) {
        setShowNewMessages(false);
        setNewMessageCount(0);
      }
    };

    scroller.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => scroller.removeEventListener("scroll", onScroll);
  }, [showLoadingSkeleton]);

  useLayoutEffect(() => {
    if (showLoadingSkeleton) return;
    const nextIds = new Set(messages.map((message) => message.id));
    let added = 0;
    for (const id of nextIds) {
      if (!seenMessageIdsRef.current.has(id)) added += 1;
    }

    if (added > 0) {
      requestAnimationFrame(() => {
        for (const id of nextIds) seenMessageIdsRef.current.add(id);
      });
    }

    if (added > 0 && !atBottomRef.current) {
      setShowNewMessages(true);
      setNewMessageCount((prev) => prev + added);
    }
  }, [showLoadingSkeleton, messages]);

  useLayoutEffect(() => {
    if (!openReactionPickerId) return;
    if (messages.some((message) => message.id === openReactionPickerId)) return;
    setOpenReactionPickerId(null);
  }, [messages, openReactionPickerId]);

  useLayoutEffect(() => {
    if (!openActionsMenuId) return;
    if (messages.some((message) => message.id === openActionsMenuId)) return;
    setOpenActionsMenuId(null);
  }, [messages, openActionsMenuId]);

  function scrollToBottom() {
    const scroller = resolveScrollHost(scrollerRef.current);
    const anchor = bottomAnchorRef.current;
    if (!scroller || !anchor) return;
    anchor.scrollIntoView({ block: "end", behavior: "smooth" });
    atBottomRef.current = true;
    setShowNewMessages(false);
    setNewMessageCount(0);
  }

  function toggleVoice(message: ChatMessage) {
    const url = message.voiceUrl;
    if (!url) return;
    const audio = audioRef.current;
    if (!audio) return;

    const currentId = activeVoiceMessageIdRef.current;
    const nextId = message.id;

    // Toggle current
    if (currentId === nextId) {
      if (!audio.paused) audio.pause();
      else void audio.play().catch(() => {});
      return;
    }

    // Stop previous
    if (!audio.paused) audio.pause();
    if (currentId) positionByMessageIdRef.current.set(currentId, audio.currentTime);

    // Switch
    activeVoiceMessageIdRef.current = nextId;
    setActiveVoiceMessageId(nextId);
    setVoiceProgress(0);
    audio.src = url;
    const resumeAt = positionByMessageIdRef.current.get(nextId) ?? 0;
    audio.currentTime = resumeAt;
    void audio.play().catch(() => {});
  }

  function voiceDurationLabel(message: ChatMessage): string {
    const ms = message.voiceDurationMs != null && message.voiceDurationMs > 0 ? message.voiceDurationMs : null;
    if (ms != null) return formatDurationMs(ms) ?? "";
    const seconds = durationByMessageId[message.id];
    if (seconds != null && Number.isFinite(seconds) && seconds > 0) return formatDurationMs(Math.round(seconds * 1000)) ?? "";
    return "";
  }

  function triggerReaction(message: ChatMessage, emoji: ChatReactionEmoji) {
    if (!onReactMessage || message.rawId == null) return;
    setOpenReactionPickerId(null);
    onReactMessage(message.rawId, emoji);
  }

  const compactEmpty = !showLoadingSkeleton && visibleMessages.length === 0 && emptyState == null;

  return (
    <div
      className={["chat-thread-body", compactEmpty ? "chat-thread-body--empty-compact" : ""].filter(Boolean).join(" ")}
    >
      <div ref={scrollerRef} data-testid="chat-messages" className="chat-thread-scroller" aria-label={historyAria.text}>
        {showLoadingSkeleton ? (
          <div className="chat-thread-skeleton" aria-busy>
            {[0, 1, 2, 3, 4].map((index) => (
              <Skeleton
                key={index}
                style={{
                  width: index % 2 === 0 ? "74%" : "62%",
                  height: 56,
                  borderRadius: 22,
                  marginLeft: index % 2 === 0 ? 0 : "auto",
                }}
              />
            ))}
          </div>
        ) : visibleMessages.length === 0 ? (
          emptyState ? (
            <div className="chat-thread-empty">{emptyState}</div>
          ) : null
        ) : (
          <div className="chat-message-list">
            {hasMoreOlder && onLoadOlder ? (
              <div style={{ padding: "10px 0", display: "flex", justifyContent: "center" }}>
                <button
                  type="button"
                  className="chat-message-load-older"
                  onClick={onLoadOlder}
                  disabled={olderLoading}
                  style={{
                    borderRadius: 999,
                    border: "1px solid rgba(255,255,255,0.12)",
                    background: "rgba(255,255,255,0.06)",
                    color: "inherit",
                    padding: "8px 14px",
                    fontSize: 13,
                    cursor: olderLoading ? "wait" : "pointer",
                    opacity: olderLoading ? 0.7 : 1,
                  }}
                >
                  {olderLoading ? t("common.loading") : t("chat.list.loadOlder")}
                </button>
              </div>
            ) : null}
            {rendered.map(({ message, ownMessage, groupStart, groupEnd, showDayMarker, isNew }, rowIndex) => {
              const isLastRow = rowIndex === rendered.length - 1;
              const isPartner = !ownMessage;
              const showPartnerAvatar = isPartner && groupStart;
              const showMyAvatar = ownMessage && groupStart;
              const timeLabel = formatMessageTime(message.timestamp, locale);
              const replyTarget =
                message.replyToMessageId && messageById.has(message.replyToMessageId)
                  ? messageById.get(message.replyToMessageId) || null
                  : null;
              const reactionEntries = Object.entries(message.reactions ?? {})
                .filter(([, count]) => Number.isFinite(count) && count > 0)
                .sort(([leftEmoji], [rightEmoji]) => reactionSortIndex(leftEmoji) - reactionSortIndex(rightEmoji));
              const pendingReaction =
                message.rawId != null ? reactionPendingByMessageId?.[String(message.rawId)] ?? null : null;
              const pickerOpen = openReactionPickerId === message.id;

              return (
                <div key={message.id}>
                  {showDayMarker ? <div className="chat-day-separator">{formatDayLabel(message.timestamp, locale, t("chat.list.dayFallback"))}</div> : null}
                  <div
                    className={[
                      "chat-message-row",
                      ownMessage ? "chat-message-row--own" : "chat-message-row--partner",
                      groupStart ? "chat-message-row--group-start" : "chat-message-row--group-continue",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                  >
                    {isPartner ? (
                      showPartnerAvatar ? (
                        <Link
                          href={`/people/${partnerUserId}`}
                          prefetch={false}
                          className="chat-message-avatar-link"
                            aria-label={t("chat.list.openPartnerProfile", { name: partnerName })}
                        >
                          <ChatAvatar
                            className="chat-message-avatar"
                            name={partnerName}
                            src={partnerAvatarUrl}
                            alt={t("chat.list.avatarAlt", { name: partnerName })}
                          />
                        </Link>
                      ) : (
                        <span className="chat-message-avatar-spacer" aria-hidden />
                      )
                    ) : null}

                    <div
                      className={[
                        "chat-message-stack",
                        ownMessage ? "chat-message-stack--own" : "chat-message-stack--partner",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                    >
                      <div
                        className={[
                          "chat-message-bubble",
                          ownMessage ? "chat-message-bubble--own" : "chat-message-bubble--partner",
                          groupStart ? "chat-message-bubble--group-start" : "chat-message-bubble--group-continue",
                          isNew ? "chat-message-bubble--new" : "",
                          !ownMessage && partnerReplyGlowId && String(message.id) === partnerReplyGlowId
                            ? "chat-message-bubble--reply-glow"
                            : "",
                          message.clientStatus === "sending" ? "chat-message-bubble--sending" : "",
                          message.clientStatus === "failed" ? "chat-message-bubble--failed" : "",
                          "",
                        ]
                          .filter(Boolean)
                          .join(" ")}
                      >
                        {/* AI must never appear as a participant in message history. */}
                        {replyTarget ? (
                          <div className="chat-message-reply">
                            <div className="chat-message-reply__label">
                              {renderDebugText(t("chat.list.replyingTo"), { component: "ChatMessageList", prop: "replyingToLabel" })}
                            </div>
                            <div className="chat-message-reply__text">{replyTarget.content}</div>
                          </div>
                        ) : null}
                        {message.voiceUrl ? (
                          <div className="chat-voice-bubble">
                            <button
                              type="button"
                              className="chat-voice-bubble__play"
                              onClick={() => toggleVoice(message)}
                              aria-label={voicePlaying && activeVoiceMessageId === message.id ? t("chat.list.pause") : t("chat.list.play")}
                            >
                              {voicePlaying && activeVoiceMessageId === message.id ? "❚❚" : "▶"}
                            </button>
                            <div className="chat-voice-bubble__track" aria-hidden>
                              <div
                                className="chat-voice-bubble__fill"
                                style={{
                                  width:
                                    activeVoiceMessageId === message.id ? `${Math.round(voiceProgress * 100)}%` : "0%",
                                }}
                              />
                            </div>
                            <div className="chat-voice-bubble__meta">
                              <span className="chat-voice-bubble__duration">{voiceDurationLabel(message)}</span>
                              {message.clientStatus === "sending" ? <span className="chat-spinner chat-voice-bubble__spinner" aria-hidden /> : null}
                            </div>
                          </div>
                        ) : null}
                        {message.content ? <p className="chat-message-bubble__text">{message.content}</p> : null}
                        {message.clientStatus === "failed" && message.voiceUrl ? (
                          <div className="chat-voice-bubble__error">
                            <span className="chat-voice-bubble__error-text">{t("chat.list.failedToSend")}</span>
                            {message.clientTempId && onRetryVoiceMessage ? (
                              <button
                                type="button"
                                className="chat-voice-bubble__retry"
                                onClick={() => onRetryVoiceMessage(message.clientTempId!)}
                              >
                                {t("chat.list.retry")}
                              </button>
                            ) : null}
                          </div>
                        ) : null}
                        {message.aiGenerated && ownMessage && groupEnd ? (
                          <div className="caption" style={{ opacity: 0.72, marginTop: 4, fontSize: 11 }}>
                            ✨ {t("chat.list.aiDraftHint")}
                          </div>
                        ) : null}
                        {timeLabel ? (
                          <time
                            className={[
                              "chat-message-bubble__time",
                              groupEnd ? "chat-message-bubble__time--shown" : "chat-message-bubble__time--hover",
                            ].join(" ")}
                            dateTime={message.timestamp ?? undefined}
                          >
                            {timeLabel}
                          </time>
                        ) : null}
                        {ownMessage && groupEnd ? (
                          <div
                            className="chat-message-bubble__delivery caption"
                            style={{ opacity: 0.68, marginTop: 2, fontSize: 11, textAlign: "right" }}
                          >
                            {message.clientStatus === "sending"
                              ? t("chat.list.sending")
                              : message.readByPartner
                                ? t("chat.list.readReceipt")
                                : message.rawId != null
                                  ? t("chat.list.sent")
                                  : ""}
                          </div>
                        ) : null}
                      </div>

                      {message.rawId != null && (onReplyMessage || onReactMessage || onDeleteThread || onIgnorePartner || onUnignorePartner) ? (
                        <div className="chat-message-actions" aria-label={t("chat.list.messageActionsAria")}>
                          <button
                            type="button"
                            data-testid="message-actions-button"
                            className="chat-message-action chat-message-action--menu"
                            aria-label={locale === "uk" ? "Дії" : "More actions"}
                            aria-expanded={openActionsMenuId === message.id}
                            onClick={() => setOpenActionsMenuId((current) => (current === message.id ? null : message.id))}
                          >
                            ⋯
                          </button>
                          {onReplyMessage ? (
                            <button type="button" className="chat-message-action" onClick={() => onReplyMessage(message)}>
                              {renderDebugText(t("chat.list.reply"), { component: "ChatMessageList", prop: "replyButton" })}
                            </button>
                          ) : null}
                          {onReactMessage ? (
                            <button
                              type="button"
                              className={[
                                "chat-message-action",
                                "chat-message-action--reaction",
                                pickerOpen ? "chat-message-action--active" : "",
                              ]
                                .filter(Boolean)
                                .join(" ")}
                              aria-expanded={pickerOpen}
                              aria-label={t("chat.list.addReaction")}
                              disabled={Boolean(pendingReaction)}
                              onClick={() => setOpenReactionPickerId((current) => (current === message.id ? null : message.id))}
                            >
                              {renderDebugText(pendingReaction ? t("chat.list.reacting") : t("chat.list.react"), {
                                component: "ChatMessageList",
                                prop: "reactionButton",
                              })}
                            </button>
                          ) : null}
                        </div>
                      ) : null}

                      {openActionsMenuId === message.id ? (
                        <div
                          className={[
                            "chat-message-actions-menu",
                            ownMessage ? "chat-message-actions-menu--own" : "chat-message-actions-menu--partner",
                          ]
                            .filter(Boolean)
                            .join(" ")}
                          role="menu"
                        >
                          {onReplyMessage ? (
                            <button
                              type="button"
                              className="chat-message-actions-menu__item"
                              role="menuitem"
                              onClick={() => {
                                setOpenActionsMenuId(null);
                                onReplyMessage(message);
                              }}
                            >
                              {t("chat.list.reply")}
                            </button>
                          ) : null}
                          {onReactMessage ? (
                            <button
                              type="button"
                              className="chat-message-actions-menu__item"
                              role="menuitem"
                              onClick={() => {
                                setOpenActionsMenuId(null);
                                setOpenReactionPickerId((current) => (current === message.id ? null : message.id));
                              }}
                            >
                              {t("chat.list.react")}
                            </button>
                          ) : null}
                          {ownMessage && canDeleteThread && onDeleteThread ? (
                            <button
                              type="button"
                              className="chat-message-actions-menu__item"
                              role="menuitem"
                              onClick={() => {
                                setOpenActionsMenuId(null);
                                onDeleteThread();
                              }}
                            >
                              {t("chat.actions.delete")}
                            </button>
                          ) : null}
                          {!ownMessage && (partnerIgnored ? onUnignorePartner : onIgnorePartner) ? (
                            <button
                              type="button"
                              className="chat-message-actions-menu__item"
                              role="menuitem"
                              onClick={() => {
                                setOpenActionsMenuId(null);
                                if (partnerIgnored) onUnignorePartner?.();
                                else onIgnorePartner?.();
                              }}
                            >
                              {partnerIgnored ? t("chat.actions.unignore") : t("chat.actions.ignore")}
                            </button>
                          ) : null}
                        </div>
                      ) : null}

                      {pickerOpen && onReactMessage && message.rawId != null ? (
                        <div
                          className={[
                            "chat-message-reaction-picker",
                            ownMessage ? "chat-message-reaction-picker--own" : "chat-message-reaction-picker--partner",
                          ]
                            .filter(Boolean)
                            .join(" ")}
                          role="menu"
                          aria-label={t("chat.list.chooseReaction")}
                        >
                          {CHAT_REACTION_EMOJIS.map((emoji) => {
                            const mine = message.myReactions?.includes(emoji) ?? false;
                            return (
                              <button
                                key={emoji}
                                type="button"
                                className={[
                                  "chat-message-reaction-picker__option",
                                  mine ? "chat-message-reaction-picker__option--mine" : "",
                                  pendingReaction === emoji ? "chat-message-reaction-picker__option--pending" : "",
                                ]
                                  .filter(Boolean)
                                  .join(" ")}
                                disabled={Boolean(pendingReaction)}
                                onClick={() => triggerReaction(message, emoji)}
                              >
                                {emoji}
                              </button>
                            );
                          })}
                        </div>
                      ) : null}

                      {reactionEntries.length > 0 ? (
                        <div
                          className={[
                            "chat-message-reactions",
                            ownMessage ? "chat-message-reactions--own" : "chat-message-reactions--partner",
                          ]
                            .filter(Boolean)
                            .join(" ")}
                          aria-label={t("chat.list.reactionsAria")}
                        >
                          {reactionEntries.map(([emoji, count]) => {
                            const canToggleKnownReaction =
                              onReactMessage != null &&
                              message.rawId != null &&
                              CHAT_REACTION_EMOJIS.includes(emoji as ChatReactionEmoji);
                            return (
                              <button
                                key={emoji}
                                type="button"
                                className={[
                                  "chat-message-reaction",
                                  message.myReactions?.includes(emoji) ? "chat-message-reaction--mine" : "",
                                  pendingReaction === emoji ? "chat-message-reaction--pending" : "",
                                ]
                                  .filter(Boolean)
                                  .join(" ")}
                                aria-pressed={message.myReactions?.includes(emoji) ?? false}
                                disabled={!canToggleKnownReaction || Boolean(pendingReaction)}
                                onClick={() => triggerReaction(message, emoji as ChatReactionEmoji)}
                              >
                                <span className="chat-message-reaction__emoji">{emoji}</span>
                                <span className="chat-message-reaction__count">{count}</span>
                              </button>
                            );
                          })}
                        </div>
                      ) : null}

                      {ownMessage && groupEnd ? (
                        <div className="chat-message-meta">
                          {message.clientStatus === "sending" ? (
                            <span className="chat-message-meta__label">
                              {renderDebugText(t("chat.list.sending"), { component: "ChatMessageList", prop: "sendingLabel" })}
                            </span>
                          ) : null}
                          {message.clientStatus === "sent" ? (
                            <span className="chat-message-meta__label">
                              {renderDebugText(t("chat.list.sent"), { component: "ChatMessageList", prop: "sentLabel" })}
                            </span>
                          ) : null}
                          {message.clientStatus === "failed" ? (
                            <>
                              <span className="chat-message-meta__label chat-message-meta__label--error">
                                {renderDebugText(t("chat.list.failed"), { component: "ChatMessageList", prop: "failedLabel" })}
                              </span>
                              {message.clientTempId && onRetryMessage ? (
                                <button
                                  type="button"
                                  className="chat-message-meta__retry"
                                  onClick={() => onRetryMessage(message.clientTempId!)}
                                >
                                  {renderDebugText(t("chat.list.retry"), { component: "ChatMessageList", prop: "retryButton" })}
                                </button>
                              ) : null}
                            </>
                          ) : null}
                        </div>
                      ) : null}
                    </div>

                    {ownMessage ? (
                      showMyAvatar ? (
                        <Link
                          href="/profile"
                          prefetch={false}
                          className="chat-message-avatar-link chat-message-avatar-link--me"
                          aria-label={t("chat.list.openMyProfile")}
                        >
                          <ChatAvatar className="chat-message-avatar" name={myName} src={myAvatarUrl} alt={t("chat.list.myAvatarAlt")} />
                        </Link>
                      ) : (
                        <span className="chat-message-avatar-spacer" aria-hidden />
                      )
                    ) : null}
                  </div>
                {isLastRow && isPartner && inlineUnderLastPartnerMessage ? (
                  <div className="chat-inline-reply-suggestions">{inlineUnderLastPartnerMessage}</div>
                ) : null}
                </div>
              );
            })}
            {showPartnerTyping ? (
              <div
                className="chat-message-row chat-message-row--partner chat-message-row--group-start"
                aria-live="polite"
                aria-label={partnerTypingAriaLabel || t("chat.list.partnerTyping", { name: partnerName })}
              >
                <Link
                  href={`/people/${partnerUserId}`}
                  prefetch={false}
                  className="chat-message-avatar-link"
                  aria-label={t("chat.list.openPartnerProfile", { name: partnerName })}
                >
                  <ChatAvatar
                    className="chat-message-avatar"
                    name={partnerName}
                    src={partnerAvatarUrl}
                    alt={t("chat.list.avatarAlt", { name: partnerName })}
                  />
                </Link>
                <div className="chat-message-stack chat-message-stack--partner">
                  <div className="chat-message-bubble chat-message-bubble--partner chat-message-bubble--group-start chat-message-typing">
                    <span className="chat-message-typing__dot" />
                    <span className="chat-message-typing__dot" />
                    <span className="chat-message-typing__dot" />
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        )}

        {afterMessagesContent ? <div className="chat-thread-scroller-tail">{afterMessagesContent}</div> : null}

        <div ref={bottomAnchorRef} aria-hidden />

        {showNewMessages ? (
          <button type="button" className="chat-new-messages" onClick={scrollToBottom}>
            {renderDebugText(t("chat.list.newMessages", { count: newMessageCount }), {
              component: "ChatMessageList",
              prop: "newMessagesButton",
            })}
          </button>
        ) : null}
      </div>
    </div>
  );
}
