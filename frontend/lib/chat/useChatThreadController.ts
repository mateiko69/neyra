"use client";

import { startTransition, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ApiUnauthorizedError, AUTH_UNAUTHORIZED_EVENT, apiFetch, isAuthSessionTerminated } from "../api";
import {
  CHAT_THREAD_POLL_MS,
  deleteChatByMatchId,
  emitChatSync,
  fetchChatViewer,
  fetchThreadMessages,
  fetchThreadPartnerProfile,
  postAiConversationOpener,
  hasChatSession,
  isNonFatalPollError,
  reactToMessage,
  sendThreadMessage,
  uploadVoiceNote,
  syncUnreadStateForOpenedThread,
  CHAT_SYNC_EVENT,
  VIEWER_REFRESH_EVENT,
  type ChatSyncDetail,
  type MessageAssistMeta,
} from "./api";
import { debugChat } from "./debug";
import { isBenignChatRequestFailure } from "./errors";
import { i18nKey, rawI18nText, resolveI18nText, type I18nText } from "../i18n/message";
import { translateApiUserMessage } from "../i18n/translateApiUserMessage";
import { appendThreadMessage, conversationContext, messageKey, messagesSnapshotEqual, sortMessages } from "./normalize";
import { getChatThreadHeaderSeed } from "./threadHeaderSeed";
import type { ChatThreadHeaderSeed } from "./threadHeaderSeed";
import {
  CHAT_REACTION_EMOJIS,
  type ChatMessage,
  type ChatPartnerProfile,
  type ChatReactionEmoji,
  type ChatSendResult,
  type ChatViewer,
} from "./types";
import type { VoiceDraft } from "../../app/components/chat/ChatComposer";
import { getStoredLocale, useI18nController } from "../i18n";
import { peekMyPrimaryPhoto, setMyPrimaryPhotoCache } from "../meProfileCache";
import { primaryPhotoFromList } from "../media";
import { blockUser, ignoreUser, reportUser, unignoreUser, type ReportCategory } from "../safety/api";

function mergeServerWithPendingReactions(
  serverMessages: ChatMessage[],
  localMessages: ChatMessage[],
  pendingByRawId: Record<string, ChatReactionEmoji>,
): ChatMessage[] {
  const pendingKeys = Object.keys(pendingByRawId || {});
  if (pendingKeys.length === 0) return serverMessages;
  const localByRawId = new Map<number, ChatMessage>();
  for (const m of localMessages) {
    if (m.rawId != null) localByRawId.set(m.rawId, m);
  }
  return serverMessages.map((m) => {
    if (m.rawId == null) return m;
    if (!pendingByRawId[String(m.rawId)]) return m;
    const local = localByRawId.get(m.rawId);
    if (!local) return m;
    return {
      ...m,
      reactions: local.reactions,
      myReactions: local.myReactions,
    };
  });
}

function routePartnerUserId(raw: string | string[] | undefined): number | null {
  const value = Array.isArray(raw) ? raw[0] : raw;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 1) return null;
  return Math.trunc(parsed);
}

function isBlockedChatErrorMessage(message: string): boolean {
  return message.toLowerCase().includes("blocked");
}

function isBlockedChatError(message: I18nText): boolean {
  if (!message) return false;
  if ("raw" in message) return isBlockedChatErrorMessage(message.raw);
  return message.key === "chat.thread.errors.blocked";
}

function knownMyReactions(message: ChatMessage): ChatReactionEmoji[] {
  return Array.from(
    new Set(
      (message.myReactions ?? []).filter((emoji): emoji is ChatReactionEmoji =>
        CHAT_REACTION_EMOJIS.includes(emoji as ChatReactionEmoji),
      ),
    ),
  );
}

function withMessageByRawId(
  messages: ChatMessage[],
  messageId: number,
  update: (message: ChatMessage) => ChatMessage,
): ChatMessage[] {
  let changed = false;
  const next = messages.map((message) => {
    if (message.rawId !== messageId) return message;
    changed = true;
    return update(message);
  });
  return changed ? next : messages;
}

function withMessageById(
  messages: ChatMessage[],
  messageId: string,
  update: (message: ChatMessage) => ChatMessage,
): ChatMessage[] {
  let changed = false;
  const next = messages.map((message) => {
    if (message.id !== messageId) return message;
    changed = true;
    return update(message);
  });
  return changed ? next : messages;
}

function mergeDeliveredThreadMessage(
  messages: ChatMessage[],
  clientTempId: string,
  delivered: ChatMessage,
): ChatMessage[] {
  const optimistic = messages.find((message) => message.id === clientTempId) ?? null;
  const withoutTemp = messages.filter((message) => message.id !== clientTempId);
  const sent: ChatMessage = {
    ...delivered,
    clientStatus: "sent",
    clientTempId,
    createdAt: delivered.createdAt ?? delivered.timestamp ?? optimistic?.createdAt ?? optimistic?.timestamp ?? null,
    timestamp: delivered.timestamp ?? optimistic?.timestamp ?? null,
    replyToMessageId: delivered.replyToMessageId ?? optimistic?.replyToMessageId ?? null,
    voiceUrl: delivered.voiceUrl ?? optimistic?.voiceUrl ?? null,
    voiceMime: delivered.voiceMime ?? optimistic?.voiceMime ?? null,
    voiceDurationMs: delivered.voiceDurationMs ?? optimistic?.voiceDurationMs ?? null,
    isDeleted: delivered.isDeleted ?? optimistic?.isDeleted,
    deletedAt: delivered.deletedAt ?? optimistic?.deletedAt ?? null,
  };

  if (sent.rawId != null) {
    const dupIdx = withoutTemp.findIndex((m) => m.rawId === sent.rawId);
    if (dupIdx !== -1) {
      const next = [...withoutTemp];
      next[dupIdx] = { ...withoutTemp[dupIdx], ...sent, clientStatus: "sent", clientTempId };
      return sortMessages(next);
    }
  }

  const sk = messageKey(sent);
  if (withoutTemp.some((m) => messageKey(m) === sk)) {
    return sortMessages(withoutTemp);
  }

  return appendThreadMessage(withoutTemp, sent);
}

function mergeSendResultMessages(messages: ChatMessage[], clientTempId: string, result: Extract<ChatSendResult, { kind: "sent" }>): ChatMessage[] {
  let next = mergeDeliveredThreadMessage(messages, clientTempId, result.message);
  for (const extra of result.extraMessages ?? []) {
    next = appendThreadMessage(next, extra);
  }
  return next;
}

function applyReadReceipts(messages: ChatMessage[], viewerId: number | null, partnerLastReadAt: string | null): ChatMessage[] {
  if (viewerId == null || !partnerLastReadAt) {
    return messages.map((m) => ({ ...m, readByPartner: undefined }));
  }
  const readMs = Date.parse(partnerLastReadAt);
  if (!Number.isFinite(readMs)) {
    return messages.map((m) => ({ ...m, readByPartner: undefined }));
  }
  return messages.map((m) => {
    if (m.senderId !== viewerId) return { ...m, readByPartner: undefined };
    const ts = Date.parse(m.timestamp ?? m.createdAt ?? "");
    if (!Number.isFinite(ts)) return { ...m, readByPartner: false };
    return { ...m, readByPartner: ts <= readMs };
  });
}

function applyOptimisticReactionState(message: ChatMessage, nextMyReactions: ChatReactionEmoji[]): ChatMessage {
  const previousMine = new Set(knownMyReactions(message));
  const nextMine = new Set(nextMyReactions);
  const counts = { ...(message.reactions ?? {}) };

  for (const emoji of previousMine) {
    if (nextMine.has(emoji)) continue;
    const nextCount = (counts[emoji] ?? 0) - 1;
    if (nextCount > 0) counts[emoji] = nextCount;
    else delete counts[emoji];
  }

  for (const emoji of nextMine) {
    if (previousMine.has(emoji)) continue;
    counts[emoji] = (counts[emoji] ?? 0) + 1;
  }

  return {
    ...message,
    reactions: Object.keys(counts).length > 0 ? counts : undefined,
    myReactions: nextMyReactions.length > 0 ? nextMyReactions : undefined,
  };
}

export function useChatThreadController() {
  const params = useParams<{ partnerUserId?: string | string[] }>();
  const router = useRouter();
  const routerRef = useRef(router);
  routerRef.current = router;
  const { t } = useI18nController();
  const partnerUserId = routePartnerUserId(params.partnerUserId);

  const [viewer, setViewer] = useState<ChatViewer | null>(null);
  const [partner, setPartner] = useState<ChatPartnerProfile | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [sending, setSending] = useState(false);
  const [isSendingVoice, setIsSendingVoice] = useState(false);
  const [voiceSendPhase, setVoiceSendPhase] = useState<"idle" | "uploading" | "posting" | "failed">("idle");
  const [voiceSendError, setVoiceSendError] = useState<string>("");
  const [loadError, setLoadError] = useState<I18nText>(null);
  const [sendError, setSendError] = useState<I18nText>(null);
  const [blockedThread, setBlockedThread] = useState(false);
  const [threadSeed, setThreadSeed] = useState<ChatThreadHeaderSeed | null>(null);
  const [myAvatarUrl, setMyAvatarUrl] = useState<string | null>(null);
  const [myCity, setMyCity] = useState<string>("");
  const [replyTo, setReplyTo] = useState<ChatMessage | null>(null);
  const [blocking, setBlocking] = useState(false);
  const [matchId, setMatchId] = useState<number | null>(null);
  const [reactionPendingByMessageId, setReactionPendingByMessageId] = useState<Record<string, ChatReactionEmoji>>({});
  const [partnerLastReadAt, setPartnerLastReadAt] = useState<string | null>(null);
  const [partnerLastActiveAt, setPartnerLastActiveAt] = useState<string | null>(null);
  const [threadHasMore, setThreadHasMore] = useState(false);
  const [openerDrafting, setOpenerDrafting] = useState(false);
  const [olderLoading, setOlderLoading] = useState(false);

  const threadOpenedRef = useRef(false);
  const threadLoadGenRef = useRef(0);
  const pollIntervalRef = useRef<number | null>(null);
  const pollBusyRef = useRef(false);
  const sendingRef = useRef(false);
  const lastTempMessageRef = useRef<{ clientTempId: string; content: string } | null>(null);
  const activeThreadPartnerRef = useRef<number | null>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  const reactionPendingRef = useRef<Record<string, ChatReactionEmoji>>({});
  const reactionRequestRef = useRef(new Map<number, { emoji: ChatReactionEmoji; promise: Promise<void> }>());
  const voiceRetryRef = useRef(
    new Map<
      string,
      {
        blob: Blob;
        mime: string;
        durationMs: number | null;
        caption: string;
        uploadedUrl?: string;
        uploadedResolvedUrl?: string;
      }
    >(),
  );
  const [partnerTyping, setPartnerTyping] = useState(false);
  const demoReplyDelayTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const viewerRef = useRef<ChatViewer | null>(null);

  useEffect(() => {
    viewerRef.current = viewer;
  }, [viewer]);

  useEffect(() => {
    return () => {
      if (demoReplyDelayTimerRef.current) {
        clearTimeout(demoReplyDelayTimerRef.current);
        demoReplyDelayTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (partnerUserId == null) return;
    setPartnerTyping(false);
    if (demoReplyDelayTimerRef.current) {
      clearTimeout(demoReplyDelayTimerRef.current);
      demoReplyDelayTimerRef.current = null;
    }
  }, [partnerUserId]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    reactionPendingRef.current = reactionPendingByMessageId;
  }, [reactionPendingByMessageId]);

  const localizeChatMessage = useCallback((message: string): NonNullable<I18nText> => {
    switch (message) {
      case "Could not load this conversation.":
        return i18nKey("chat.thread.errors.loadConversation");
      case "User is blocked.":
        return i18nKey("chat.thread.errors.blocked");
      case "Please wait for your account to load, then try again.":
        return i18nKey("chat.thread.errors.waitForAccount");
      case "Message failed to send.":
        return i18nKey("chat.thread.errors.sendFailed");
      case "Invalid recipient - open this chat from your inbox or matches.":
      case "Invalid recipient — open this chat from your inbox or matches.":
        return i18nKey("chat.thread.errors.invalidRecipient");
      case "Message cannot be empty.":
        return i18nKey("chat.thread.errors.emptyMessage");
      case "The server returned an unexpected message payload.":
        return i18nKey("chat.thread.errors.unexpectedPayload");
      case "Could not block user.":
        return i18nKey("chat.thread.errors.blockUser");
      case "Thanks - your report was received.":
        return i18nKey("chat.thread.report.received");
      case "Could not report user.":
        return i18nKey("chat.thread.errors.reportUser");
      default: {
        const u = translateApiUserMessage(message, t).trim();
        if (!u) return i18nKey("chat.thread.errors.sendFailed");
        return rawI18nText(u);
      }
    }
  }, [t]);

  const localizeRewriteSuggestion = useCallback(
    (suggestion: string): NonNullable<I18nText> => {
      const u = translateApiUserMessage(suggestion.trim(), t).trim();
      if (!u) return i18nKey("chat.thread.errors.sendFailed");
      return rawI18nText(u);
    },
    [t],
  );

  const formatChatErrorMessage = useCallback(
    (error: unknown, fallbackKey: string): NonNullable<I18nText> | null => {
      if (isBenignChatRequestFailure(error)) return null;
      if (error instanceof Error && error.message.trim()) {
        return localizeChatMessage(error.message.trim());
      }
      return i18nKey(fallbackKey);
    },
    [localizeChatMessage],
  );

  const clearThreadPolling = () => {
    if (pollIntervalRef.current != null) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    pollBusyRef.current = false;
  };

  const loadThreadSnapshot = useCallback(
    async (chatPartnerUserId: number, options: { manual?: boolean; loadGen?: number } = {}): Promise<boolean> => {
      if (options.manual) setRefreshing(true);
      else setLoading(true);

      setLoadError(null);
      setBlockedThread(false);

      const superseded = () => options.loadGen != null && options.loadGen !== threadLoadGenRef.current;

      try {
        const cachedSelfAvatar = peekMyPrimaryPhoto();
        if (cachedSelfAvatar !== undefined) {
          setMyAvatarUrl(cachedSelfAvatar);
        }
        const meProfilePromise =
          cachedSelfAvatar !== undefined
            ? Promise.resolve(null)
            : apiFetch("/profiles/me", { metaReason: "chat-me-profile" }).catch(() => null);

        const [viewerResult, partnerResult, messagesResult, meProfileResult] = await Promise.allSettled([
          fetchChatViewer(),
          fetchThreadPartnerProfile(chatPartnerUserId),
          fetchThreadMessages(chatPartnerUserId, options.manual ? "chat-thread-manual" : "chat-thread-initial"),
          meProfilePromise,
        ]);

        if (superseded()) return false;

        if (
          (viewerResult.status === "rejected" && isBenignChatRequestFailure(viewerResult.reason)) ||
          (partnerResult.status === "rejected" && isBenignChatRequestFailure(partnerResult.reason)) ||
          (messagesResult.status === "rejected" && isBenignChatRequestFailure(messagesResult.reason))
        ) {
          return false;
        }

        if (messagesResult.status === "rejected") {
          const message = formatChatErrorMessage(messagesResult.reason, "chat.thread.errors.loadConversation");
          if (message && !superseded()) {
            const blocked = isBlockedChatError(message);
            setBlockedThread(blocked);
            setLoadError(message);
            setMessages([]);
            setMatchId(null);
            setPartnerLastReadAt(null);
            setPartnerLastActiveAt(null);
            setThreadHasMore(false);
            if (blocked) setSendError(i18nKey("chat.thread.errors.blocked"));
          }
          return false;
        }

        if (superseded()) return false;

        setViewer(viewerResult.status === "fulfilled" ? viewerResult.value : null);
        setPartner(partnerResult.status === "fulfilled" ? partnerResult.value : null);
        setMatchId(messagesResult.value.matchId);
        setPartnerLastReadAt(messagesResult.value.partnerLastReadAt);
        setPartnerLastActiveAt(messagesResult.value.partnerLastActiveAt);
        setThreadHasMore(messagesResult.value.threadHasMore);
        const vid =
          viewerResult.status === "fulfilled" && viewerResult.value ? viewerResult.value.userId : null;
        setMessages(
          applyReadReceipts(
            mergeServerWithPendingReactions(
              messagesResult.value.messages,
              messagesRef.current,
              reactionPendingRef.current,
            ),
            vid,
            messagesResult.value.partnerLastReadAt,
          ),
        );
        setBlockedThread(false);

        if (meProfileResult.status === "fulfilled" && meProfileResult.value) {
          const raw = meProfileResult.value as Record<string, unknown> | null;
          const photoUrls = typeof raw?.photo_urls === "string" ? raw.photo_urls : (raw?.photo_urls as unknown);
          const primary = primaryPhotoFromList(photoUrls as any) || null;
          setMyPrimaryPhotoCache(primary);
          setMyAvatarUrl(primary);
          const cityRaw = raw && typeof raw === "object" ? (raw as any).city : "";
          setMyCity(typeof cityRaw === "string" ? cityRaw.trim() : "");
        }

        if (!threadOpenedRef.current) {
          threadOpenedRef.current = true;
          void syncUnreadStateForOpenedThread(chatPartnerUserId);
        }

        return true;
      } finally {
        if (!superseded()) {
          if (!options.manual) setLoading(false);
          if (options.manual) setRefreshing(false);
        }
      }
    },
    [formatChatErrorMessage],
  );

  const pollThreadMessages = useCallback(async (chatPartnerUserId: number) => {
    if (isAuthSessionTerminated() || !hasChatSession()) {
      clearThreadPolling();
      return;
    }
    if (pollBusyRef.current || sendingRef.current) return;
    if (typeof document !== "undefined" && document.visibilityState !== "visible") return;
    pollBusyRef.current = true;
    try {
      const nextMessages = await fetchThreadMessages(chatPartnerUserId, "chat-thread-poll");
      if (activeThreadPartnerRef.current !== chatPartnerUserId) return;
      startTransition(() => {
        if (nextMessages.matchId != null) {
          setMatchId(nextMessages.matchId);
        }
        setPartnerLastReadAt(nextMessages.partnerLastReadAt);
        setPartnerLastActiveAt(nextMessages.partnerLastActiveAt);
        setThreadHasMore(nextMessages.threadHasMore);
        const vid = viewerRef.current?.userId ?? null;
        const merged = applyReadReceipts(
          mergeServerWithPendingReactions(nextMessages.messages, messagesRef.current, reactionPendingRef.current),
          vid,
          nextMessages.partnerLastReadAt,
        );
        setMessages((current) => (messagesSnapshotEqual(current, merged) ? current : merged));
      });
    } catch (errorValue) {
      if (errorValue instanceof ApiUnauthorizedError) {
        clearThreadPolling();
        return;
      }
      if (!isNonFatalPollError(errorValue)) return;
    } finally {
      pollBusyRef.current = false;
    }
  }, []);

  const refetchDemoReplyUntilVisible = useCallback(
    async (chatPartnerUserId: number, sentMessage: ChatMessage): Promise<void> => {
      // Demo bots are scheduled ~5–25s server-side; keep typing on and poll until the reply lands.
      const afterRawId = sentMessage.rawId ?? null;
      const afterCreatedAt = Date.parse(sentMessage.createdAt ?? sentMessage.timestamp ?? "");
      const hasSentTimestamp = Number.isFinite(afterCreatedAt);
      const deadline = Date.now() + 32_000;
      const pollMs = 1500;

      setPartnerTyping(true);
      while (Date.now() < deadline) {
        if (activeThreadPartnerRef.current !== chatPartnerUserId) {
          setPartnerTyping(false);
          return;
        }
        await new Promise<void>((resolve) => {
          demoReplyDelayTimerRef.current = setTimeout(() => {
            demoReplyDelayTimerRef.current = null;
            resolve();
          }, pollMs);
        });
        if (activeThreadPartnerRef.current !== chatPartnerUserId) {
          setPartnerTyping(false);
          return;
        }
        try {
          const nextMessages = await fetchThreadMessages(chatPartnerUserId, "chat-thread-demo-reply-poll");
          if (activeThreadPartnerRef.current !== chatPartnerUserId) {
            setPartnerTyping(false);
            return;
          }
          setMatchId((current) => nextMessages.matchId ?? current);
          setPartnerLastReadAt(nextMessages.partnerLastReadAt);
          setPartnerLastActiveAt(nextMessages.partnerLastActiveAt);
          setThreadHasMore(nextMessages.threadHasMore);
          const vidDemo = viewerRef.current?.userId ?? null;
          const merged = applyReadReceipts(
            mergeServerWithPendingReactions(nextMessages.messages, messagesRef.current, reactionPendingRef.current),
            vidDemo,
            nextMessages.partnerLastReadAt,
          );
          setMessages((current) => (messagesSnapshotEqual(current, merged) ? current : merged));

          const hasPartnerReply = nextMessages.messages.some((message) => {
            if (message.senderId !== chatPartnerUserId) return false;
            if (afterRawId != null && message.rawId != null) return message.rawId > afterRawId;
            if (!hasSentTimestamp) return true;
            const messageTime = Date.parse(message.createdAt ?? message.timestamp ?? "");
            return Number.isFinite(messageTime) && messageTime > afterCreatedAt;
          });
          if (hasPartnerReply) {
            setPartnerTyping(false);
            return;
          }
        } catch {
          /* non-fatal */
        }
      }
      setPartnerTyping(false);
    },
    [],
  );

  // Realtime: when a websocket "messageReceived" arrives for the currently open thread,
  // fetch immediately (no waiting for the next poll). This also updates server read state
  // via GET /messages/{partnerId}, so nav badges reconcile cleanly without showing stale unread.
  useEffect(() => {
    if (partnerUserId == null) return;
    if (typeof window === "undefined") return;
    const onChatSync = (event: Event) => {
      const detail = (event as CustomEvent<ChatSyncDetail>).detail;
      if (!detail) return;
      if (detail.type === "wsReconnected") {
        if (detail.partnerUserId != null && detail.partnerUserId > 0 && detail.partnerUserId !== partnerUserId) return;
        void pollThreadMessages(partnerUserId);
        return;
      }
      if (detail.type !== "messageReceived") return;
      if (detail.partnerUserId !== partnerUserId) return;
      // Avoid collisions with poll/send; let current cycle finish.
      if (pollBusyRef.current || sendingRef.current) return;
      if (typeof document !== "undefined" && document.visibilityState !== "visible") return;
      void (async () => {
        pollBusyRef.current = true;
        try {
          const nextMessages = await fetchThreadMessages(partnerUserId, "chat-thread-ws-received");
          if (activeThreadPartnerRef.current !== partnerUserId) return;
          startTransition(() => {
            setPartnerLastReadAt(nextMessages.partnerLastReadAt);
            setPartnerLastActiveAt(nextMessages.partnerLastActiveAt);
            setThreadHasMore(nextMessages.threadHasMore);
            const vidWs = viewerRef.current?.userId ?? null;
            const merged = applyReadReceipts(
              mergeServerWithPendingReactions(nextMessages.messages, messagesRef.current, reactionPendingRef.current),
              vidWs,
              nextMessages.partnerLastReadAt,
            );
            setMessages((current) => (messagesSnapshotEqual(current, merged) ? current : merged));
          });
        } catch {
          // Non-fatal: next poll will catch up.
        } finally {
          pollBusyRef.current = false;
        }
      })();
    };
    window.addEventListener(CHAT_SYNC_EVENT, onChatSync);
    return () => window.removeEventListener(CHAT_SYNC_EVENT, onChatSync);
  }, [partnerUserId, pollThreadMessages]);

  // Refetch thread when the tab becomes visible or the network reconnects (controlled; still respects poll dedupe).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onUnauthorized = () => clearThreadPolling();
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  useEffect(() => {
    if (partnerUserId == null) return;
    if (typeof window === "undefined") return;
    const onFocusOrVisible = () => {
      if (typeof document !== "undefined" && document.visibilityState !== "visible") return;
      if (isAuthSessionTerminated() || !hasChatSession()) return;
      if (pollBusyRef.current || sendingRef.current) return;
      void pollThreadMessages(partnerUserId);
    };
    document.addEventListener("visibilitychange", onFocusOrVisible);
    window.addEventListener("online", onFocusOrVisible);
    return () => {
      document.removeEventListener("visibilitychange", onFocusOrVisible);
      window.removeEventListener("online", onFocusOrVisible);
    };
  }, [partnerUserId, pollThreadMessages]);

  // Allow other UI pieces (Copilot trial) to request viewer refresh.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onRefresh = () => {
      void fetchChatViewer()
        .then((v) => setViewer(v))
        .catch(() => {});
    };
    window.addEventListener(VIEWER_REFRESH_EVENT, onRefresh);
    return () => window.removeEventListener(VIEWER_REFRESH_EVENT, onRefresh);
  }, []);

  useEffect(() => {
    clearThreadPolling();
    setLoadError(null);
    setSendError(null);
    setVoiceSendError("");
    setVoiceSendPhase("idle");
    setDraft("");
    setReplyTo(null);

    if (partnerUserId == null) {
      activeThreadPartnerRef.current = null;
      setLoading(false);
      setViewer(null);
      setPartner(null);
      setMessages([]);
      setMatchId(null);
      setPartnerLastReadAt(null);
      setPartnerLastActiveAt(null);
      setThreadHasMore(false);
      setOpenerDrafting(false);
      setBlockedThread(false);
      setReactionPendingByMessageId({});
      reactionRequestRef.current.clear();
      voiceRetryRef.current.clear();
      return;
    }

    if (!hasChatSession()) {
      routerRef.current.replace("/login");
      return;
    }

    threadOpenedRef.current = false;
    activeThreadPartnerRef.current = partnerUserId;
    setViewer(null);
    setPartner(null);
    setMessages([]);
    setMatchId(null);
    setPartnerLastReadAt(null);
    setPartnerLastActiveAt(null);
    setThreadHasMore(false);
    setOpenerDrafting(false);
    setMyAvatarUrl(null);
    setBlockedThread(false);
    setReactionPendingByMessageId({});
    reactionRequestRef.current.clear();
    voiceRetryRef.current.clear();

    const loadGen = (threadLoadGenRef.current += 1);
    let cancelled = false;

    const boot = async () => {
      const loaded = await loadThreadSnapshot(partnerUserId, { loadGen });
      if (!loaded || cancelled) return;
      if (threadLoadGenRef.current !== loadGen) return;
      if (isAuthSessionTerminated() || !hasChatSession()) return;
      pollIntervalRef.current = window.setInterval(() => void pollThreadMessages(partnerUserId), CHAT_THREAD_POLL_MS);
    };

    void boot();
    return () => {
      cancelled = true;
      clearThreadPolling();
    };
  }, [partnerUserId, loadThreadSnapshot, pollThreadMessages]);

  useLayoutEffect(() => {
    if (partnerUserId == null) {
      setThreadSeed(null);
      return;
    }
    setThreadSeed(getChatThreadHeaderSeed(partnerUserId));
  }, [partnerUserId]);

  const displayNameForThread = useMemo(
    () => partner?.displayName?.trim() || threadSeed?.displayName?.trim() || "",
    [partner?.displayName, threadSeed?.displayName],
  );

  const showMessageSkeleton = loading && messages.length === 0;
  const showHeaderSkeleton = loading && !partner && !threadSeed?.displayName;
  const partnerAvatarUrl = partner?.primaryPhotoUrl?.trim() || threadSeed?.avatarUrl || null;
  const myName = viewer?.displayName?.trim() || t("common.you");

  const send = useCallback(
    async (opts?: {
      idempotencyKey?: string | null;
      assistMeta?: MessageAssistMeta | null;
    }): Promise<{ ok: true; rawMessageId: number | null } | { ok: false }> => {
    if (partnerUserId == null) return;
    if (blockedThread) {
      setSendError(i18nKey("chat.thread.errors.blocked"));
      return { ok: false };
    }

    const senderId = viewer?.userId ?? null;
    if (senderId == null) {
      setSendError(i18nKey("chat.thread.errors.waitForAccount"));
      return { ok: false };
    }

    const content = draft.trim();
    if (!content || sendingRef.current) return { ok: false };

    setSendError(null);
    setSending(true);
    sendingRef.current = true;

    const clientTempId = `tmp:${Date.now()}:${Math.random().toString(16).slice(2)}`;
    const createdAt = new Date().toISOString();
    const optimistic: ChatMessage = {
      id: clientTempId,
      clientTempId,
      clientStatus: "sending",
      rawId: null,
      senderId,
      receiverId: partnerUserId,
      content,
      timestamp: createdAt,
      createdAt,
      replyToMessageId: replyTo?.id ?? null,
    };
    lastTempMessageRef.current = { clientTempId, content };
    setMessages((current) => appendThreadMessage(current, optimistic));

    try {
      const result = await sendThreadMessage(
        partnerUserId,
        content,
        conversationContext(messages),
        replyTo?.id ?? null,
        null,
        opts?.idempotencyKey ?? null,
        opts?.assistMeta ?? null,
      );
      if (result.kind === "rewriteSuggested") {
        setMessages((current) => current.map((m) => (m.id === clientTempId ? { ...m, clientStatus: "failed" } : m)));
        const rewritten = localizeRewriteSuggestion(result.suggestion);
        setSendError(rewritten);
        return { ok: false };
      }
      const extras = result.extraMessages;
      if (demoReplyDelayTimerRef.current) {
        clearTimeout(demoReplyDelayTimerRef.current);
        demoReplyDelayTimerRef.current = null;
      }
      setMessages((current) => mergeDeliveredThreadMessage(current, clientTempId, result.message));
      setDraft("");
      setReplyTo(null);
      if (extras?.length && result.demoPartner) {
        setMessages((current) => {
          let next = current;
          for (const extra of extras) next = appendThreadMessage(next, extra);
          return next;
        });
      } else if (extras?.length) {
        setPartnerTyping(true);
        const delayMs = 800 + Math.floor(Math.random() * 1700);
        demoReplyDelayTimerRef.current = setTimeout(() => {
          demoReplyDelayTimerRef.current = null;
          setPartnerTyping(false);
          setMessages((current) => {
            let next = current;
            for (const extra of extras) next = appendThreadMessage(next, extra);
            return next;
          });
        }, delayMs);
      }
      if (result.demoPartner && result.demoReplyScheduled) {
        void refetchDemoReplyUntilVisible(partnerUserId, result.message);
      }
      return { ok: true, rawMessageId: result.message.rawId ?? null };
    } catch (errorValue) {
      if (isBenignChatRequestFailure(errorValue)) return;
      const message = formatChatErrorMessage(errorValue, "chat.thread.errors.sendFailed");
      if (message) {
        setSendError(message);
        if (isBlockedChatError(message)) setBlockedThread(true);
      }
      setMessages((current) => current.map((m) => (m.id === clientTempId ? { ...m, clientStatus: "failed" } : m)));
      return { ok: false };
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
    },
    [partnerUserId, blockedThread, viewer?.userId, draft, messages, replyTo, formatChatErrorMessage, localizeRewriteSuggestion, refetchDemoReplyUntilVisible],
  );

  /** Send immediately with explicit text (avoids waiting for draft state to flush). */
  const sendMessageNow = useCallback(
    async (
      contentRaw: string,
      opts?: { idempotencyKey?: string | null; assistMeta?: MessageAssistMeta | null },
    ): Promise<{ ok: true; rawMessageId: number | null } | { ok: false } | undefined> => {
      if (partnerUserId == null) return;
      if (blockedThread) {
        setSendError(i18nKey("chat.thread.errors.blocked"));
        return { ok: false };
      }

      const senderId = viewer?.userId ?? null;
      if (senderId == null) {
        setSendError(i18nKey("chat.thread.errors.waitForAccount"));
        return { ok: false };
      }

      const content = contentRaw.trim();
      if (!content || sendingRef.current) return { ok: false };

      setSendError(null);
      setSending(true);
      sendingRef.current = true;

      const clientTempId = `tmp:${Date.now()}:${Math.random().toString(16).slice(2)}`;
      const createdAt = new Date().toISOString();
      const optimistic: ChatMessage = {
        id: clientTempId,
        clientTempId,
        clientStatus: "sending",
        rawId: null,
        senderId,
        receiverId: partnerUserId,
        content,
        timestamp: createdAt,
        createdAt,
        replyToMessageId: replyTo?.id ?? null,
      };
      lastTempMessageRef.current = { clientTempId, content };
      setMessages((current) => appendThreadMessage(current, optimistic));

      try {
      const result = await sendThreadMessage(
        partnerUserId,
        content,
        conversationContext(messages),
        replyTo?.id ?? null,
        null,
        opts?.idempotencyKey ?? null,
        opts?.assistMeta ?? null,
      );
        if (result.kind === "rewriteSuggested") {
        setMessages((current) => current.map((m) => (m.id === clientTempId ? { ...m, clientStatus: "failed" } : m)));
        const rewritten = localizeRewriteSuggestion(result.suggestion);
        setSendError(rewritten);
        return { ok: false };
      }
        const extras = result.extraMessages;
        if (demoReplyDelayTimerRef.current) {
          clearTimeout(demoReplyDelayTimerRef.current);
          demoReplyDelayTimerRef.current = null;
        }
        setMessages((current) => mergeDeliveredThreadMessage(current, clientTempId, result.message));
        setDraft("");
        setReplyTo(null);
        if (extras?.length && result.demoPartner) {
          setMessages((current) => {
            let next = current;
            for (const extra of extras) next = appendThreadMessage(next, extra);
            return next;
          });
        } else if (extras?.length) {
          setPartnerTyping(true);
          const delayMs = 800 + Math.floor(Math.random() * 1700);
          demoReplyDelayTimerRef.current = setTimeout(() => {
            demoReplyDelayTimerRef.current = null;
            setPartnerTyping(false);
            setMessages((current) => {
              let next = current;
              for (const extra of extras) next = appendThreadMessage(next, extra);
              return next;
            });
          }, delayMs);
        }
        if (result.demoPartner && result.demoReplyScheduled) {
          void refetchDemoReplyUntilVisible(partnerUserId, result.message);
        }
        return { ok: true, rawMessageId: result.message.rawId ?? null };
      } catch (errorValue) {
        if (isBenignChatRequestFailure(errorValue)) return;
        const message = formatChatErrorMessage(errorValue, "chat.thread.errors.sendFailed");
        if (message) {
          setSendError(message);
          if (isBlockedChatError(message)) setBlockedThread(true);
        }
        setMessages((current) => current.map((m) => (m.id === clientTempId ? { ...m, clientStatus: "failed" } : m)));
        return { ok: false };
      } finally {
        sendingRef.current = false;
        setSending(false);
      }
    },
    [partnerUserId, blockedThread, viewer?.userId, messages, replyTo, formatChatErrorMessage, localizeRewriteSuggestion, refetchDemoReplyUntilVisible],
  );

  const sendVoice = useCallback(
    async (draftValue: VoiceDraft, caption: string): Promise<{ ok: true } | { ok: false; error: string }> => {
      if (partnerUserId == null) return { ok: false, error: t("chat.thread.errors.invalidRecipient") };
      if (blockedThread) {
        setSendError(i18nKey("chat.thread.errors.blocked"));
        return { ok: false, error: t("chat.thread.errors.blocked") };
      }
      if (sendingRef.current || isSendingVoice) return { ok: false, error: t("chat.thread.errors.voiceBusy") };

      const senderId = viewer?.userId ?? null;
      if (senderId == null) {
        setSendError(i18nKey("chat.thread.errors.waitForAccount"));
        return { ok: false, error: t("chat.thread.errors.waitForAccount") };
      }

      setSendError(null);
      setVoiceSendError("");
      setVoiceSendPhase("uploading");
      setIsSendingVoice(true);
      sendingRef.current = true;

      const captionText = (caption ?? "").trim();
      const clientTempId = `tmpvoice:${Date.now()}:${Math.random().toString(16).slice(2)}`;
      const createdAt = new Date().toISOString();
      const optimistic: ChatMessage = {
        id: clientTempId,
        clientTempId,
        clientStatus: "sending",
        rawId: null,
        senderId,
        receiverId: partnerUserId,
        content: captionText,
        timestamp: createdAt,
        createdAt,
        replyToMessageId: replyTo?.id ?? null,
        voiceUrl: draftValue.previewUrl, // local preview until upload resolves
        voiceMime: draftValue.mime,
        voiceDurationMs: draftValue.durationMs,
      };
      setMessages((current) => appendThreadMessage(current, optimistic));
      voiceRetryRef.current.set(clientTempId, {
        blob: draftValue.blob,
        mime: draftValue.mime,
        durationMs: draftValue.durationMs,
        caption: captionText,
      });

      try {
        setVoiceSendPhase("uploading");
        const upload = await uploadVoiceNote(draftValue.blob);
        voiceRetryRef.current.set(clientTempId, {
          blob: draftValue.blob,
          mime: draftValue.mime,
          durationMs: draftValue.durationMs,
          caption: captionText,
          uploadedUrl: upload.url,
          uploadedResolvedUrl: upload.resolvedUrl,
        });
        setMessages((current) =>
          withMessageById(current, clientTempId, (message) => ({
            ...message,
            voiceUrl: upload.resolvedUrl,
            voiceMime: upload.content_type || message.voiceMime || draftValue.mime,
            voiceDurationMs: draftValue.durationMs ?? message.voiceDurationMs ?? null,
          })),
        );
        setVoiceSendPhase("posting");
        const result = await sendThreadMessage(
          partnerUserId,
          captionText,
          conversationContext(messages),
          replyTo?.id ?? null,
          { voice_url: upload.url, voice_mime: upload.content_type || draftValue.mime, voice_duration_ms: draftValue.durationMs },
        );
        if (result.kind === "rewriteSuggested") {
          setMessages((current) => current.map((m) => (m.id === clientTempId ? { ...m, clientStatus: "failed" } : m)));
          const rewritten = localizeRewriteSuggestion(result.suggestion);
          setSendError(rewritten);
          setVoiceSendPhase("failed");
          const line = resolveI18nText(rewritten, t);
          setVoiceSendError(line);
          return { ok: false, error: line };
        }
        const voiceExtras = result.extraMessages;
        if (demoReplyDelayTimerRef.current) {
          clearTimeout(demoReplyDelayTimerRef.current);
          demoReplyDelayTimerRef.current = null;
        }
        setMessages((current) => mergeDeliveredThreadMessage(current, clientTempId, result.message));
        if (voiceExtras?.length) {
          setPartnerTyping(true);
          const delayMs = 800 + Math.floor(Math.random() * 1700);
          demoReplyDelayTimerRef.current = setTimeout(() => {
            demoReplyDelayTimerRef.current = null;
            setPartnerTyping(false);
            setMessages((current) => {
              let next = current;
              for (const extra of voiceExtras) next = appendThreadMessage(next, extra);
              return next;
            });
          }, delayMs);
        }
        voiceRetryRef.current.delete(clientTempId);
        setDraft("");
        setReplyTo(null);
        setVoiceSendPhase("idle");
        return { ok: true };
      } catch (errorValue) {
        if (isBenignChatRequestFailure(errorValue)) return;
        const message = formatChatErrorMessage(errorValue, "chat.thread.errors.sendFailed");
        if (message) {
          setSendError(message);
          if (isBlockedChatError(message)) setBlockedThread(true);
          setVoiceSendError(resolveI18nText(message, t));
        }
        // If upload failed, remove the optimistic message and keep the draft in the composer.
        const likelyUploadFailure = errorValue instanceof Error && /upload/i.test(errorValue.message);
        if (likelyUploadFailure) {
          setMessages((current) => current.filter((m) => m.id !== clientTempId));
          voiceRetryRef.current.delete(clientTempId);
        } else {
          setMessages((current) => current.map((m) => (m.id === clientTempId ? { ...m, clientStatus: "failed" } : m)));
        }
        setVoiceSendPhase("failed");
        return {
          ok: false,
          error: message ? resolveI18nText(message, t) : t("chat.thread.errors.sendFailed"),
        };
      } finally {
        sendingRef.current = false;
        setIsSendingVoice(false);
      }
    },
    [partnerUserId, blockedThread, viewer?.userId, messages, replyTo, formatChatErrorMessage, isSendingVoice, t, localizeRewriteSuggestion],
  );

  const retryVoice = useCallback(
    async (clientTempId: string) => {
      if (partnerUserId == null) return;
      if (sendingRef.current || isSendingVoice) return;
      const entry = voiceRetryRef.current.get(clientTempId);
      if (!entry) return;
      const failedMessage = messages.find((message) => message.id === clientTempId) ?? null;

      setMessages((current) => current.map((m) => (m.id === clientTempId ? { ...m, clientStatus: "sending" } : m)));
      setSendError(null);
      setVoiceSendError("");
      setVoiceSendPhase(entry.uploadedUrl ? "posting" : "uploading");
      setIsSendingVoice(true);
      sendingRef.current = true;

      try {
        let voiceUrl = entry.uploadedUrl;
        let resolvedVoiceUrl = entry.uploadedResolvedUrl;
        let voiceMime = entry.mime;
        if (!voiceUrl) {
          const upload = await uploadVoiceNote(entry.blob);
          voiceUrl = upload.url;
          resolvedVoiceUrl = upload.resolvedUrl;
          voiceMime = upload.content_type || voiceMime;
          voiceRetryRef.current.set(clientTempId, {
            ...entry,
            uploadedUrl: voiceUrl,
            uploadedResolvedUrl: resolvedVoiceUrl,
          });
        }
        if (resolvedVoiceUrl) {
          setMessages((current) =>
            withMessageById(current, clientTempId, (message) => ({
              ...message,
              voiceUrl: resolvedVoiceUrl,
              voiceMime: voiceMime || message.voiceMime || null,
              voiceDurationMs: entry.durationMs ?? message.voiceDurationMs ?? null,
            })),
          );
        }

        const result = await sendThreadMessage(
          partnerUserId,
          entry.caption,
          conversationContext(messages),
          failedMessage?.replyToMessageId ?? null,
          { voice_url: voiceUrl, voice_mime: voiceMime, voice_duration_ms: entry.durationMs },
        );
        if (result.kind === "rewriteSuggested") {
          setMessages((current) => current.map((m) => (m.id === clientTempId ? { ...m, clientStatus: "failed" } : m)));
          const rewritten = localizeRewriteSuggestion(result.suggestion);
          setSendError(rewritten);
          setVoiceSendPhase("failed");
          setVoiceSendError(resolveI18nText(rewritten, t));
          return;
        }
        const voiceExtrasRetry = result.extraMessages;
        if (demoReplyDelayTimerRef.current) {
          clearTimeout(demoReplyDelayTimerRef.current);
          demoReplyDelayTimerRef.current = null;
        }
        setMessages((current) => mergeDeliveredThreadMessage(current, clientTempId, result.message));
        if (voiceExtrasRetry?.length) {
          setPartnerTyping(true);
          const delayMs = 800 + Math.floor(Math.random() * 1700);
          demoReplyDelayTimerRef.current = setTimeout(() => {
            demoReplyDelayTimerRef.current = null;
            setPartnerTyping(false);
            setMessages((current) => {
              let next = current;
              for (const extra of voiceExtrasRetry) next = appendThreadMessage(next, extra);
              return next;
            });
          }, delayMs);
        }
        voiceRetryRef.current.delete(clientTempId);
        setVoiceSendPhase("idle");
      } catch (errorValue) {
        if (isBenignChatRequestFailure(errorValue)) return;
        const message = formatChatErrorMessage(errorValue, "chat.thread.errors.sendFailed");
        if (message) setSendError(message);
        setMessages((current) => current.map((m) => (m.id === clientTempId ? { ...m, clientStatus: "failed" } : m)));
        setVoiceSendPhase("failed");
        setVoiceSendError(message ? resolveI18nText(message, t) : t("chat.thread.errors.sendFailed"));
      } finally {
        sendingRef.current = false;
        setIsSendingVoice(false);
      }
    },
    [partnerUserId, isSendingVoice, messages, formatChatErrorMessage, t, localizeRewriteSuggestion],
  );

  const retrySend = useCallback(
    async (clientTempId: string) => {
      if (partnerUserId == null) return;
      if (sendingRef.current) return;
      const senderId = viewer?.userId ?? null;
      if (senderId == null) return;

      const entry = lastTempMessageRef.current;
      const failedMessage = messages.find((message) => message.id === clientTempId) ?? null;
      const retryContent =
        entry?.clientTempId === clientTempId ? entry.content : failedMessage?.content || "";
      const content = retryContent.trim();
      if (!content) return;

      setMessages((current) => current.map((m) => (m.id === clientTempId ? { ...m, clientStatus: "sending" } : m)));
      setSendError(null);
      setSending(true);
      sendingRef.current = true;

      try {
        const result = await sendThreadMessage(
          partnerUserId,
          content,
          conversationContext(messages),
          failedMessage?.replyToMessageId ?? null,
        );
        if (result.kind === "rewriteSuggested") {
          setMessages((current) => current.map((m) => (m.id === clientTempId ? { ...m, clientStatus: "failed" } : m)));
          setSendError(localizeRewriteSuggestion(result.suggestion));
          return;
        }
        const retryExtras = result.extraMessages;
        if (demoReplyDelayTimerRef.current) {
          clearTimeout(demoReplyDelayTimerRef.current);
          demoReplyDelayTimerRef.current = null;
        }
        setMessages((current) => mergeDeliveredThreadMessage(current, clientTempId, result.message));
        if (retryExtras?.length) {
          setPartnerTyping(true);
          const delayMs = 800 + Math.floor(Math.random() * 1700);
          demoReplyDelayTimerRef.current = setTimeout(() => {
            demoReplyDelayTimerRef.current = null;
            setPartnerTyping(false);
            setMessages((current) => {
              let next = current;
              for (const extra of retryExtras) next = appendThreadMessage(next, extra);
              return next;
            });
          }, delayMs);
        }
      } catch (errorValue) {
        if (isBenignChatRequestFailure(errorValue)) return;
        setMessages((current) => current.map((m) => (m.id === clientTempId ? { ...m, clientStatus: "failed" } : m)));
        const message = formatChatErrorMessage(errorValue, "chat.thread.errors.sendFailed");
        if (message) {
          setSendError(message);
          if (isBlockedChatError(message)) setBlockedThread(true);
        }
      } finally {
        sendingRef.current = false;
        setSending(false);
      }
    },
    [partnerUserId, viewer?.userId, messages, formatChatErrorMessage, localizeRewriteSuggestion],
  );

  const refresh = useCallback(async () => {
    if (partnerUserId == null || refreshing) return;
    await loadThreadSnapshot(partnerUserId, { manual: true, loadGen: threadLoadGenRef.current });
  }, [partnerUserId, refreshing, loadThreadSnapshot]);

  const react = useCallback(
    async (messageId: number, emoji: ChatReactionEmoji) => {
      if (partnerUserId == null) return;

      const existingRequest = reactionRequestRef.current.get(messageId);
      if (existingRequest) {
        if (existingRequest.emoji === emoji) {
          debugChat("dedupe duplicate reaction click", { messageId, emoji });
          return existingRequest.promise;
        }
        debugChat("ignore reaction click while another reaction is in flight", {
          messageId,
          activeEmoji: existingRequest.emoji,
          nextEmoji: emoji,
        });
        return;
      }

      const previousSnapshot = messagesRef.current.find((message) => message.rawId === messageId);
      if (!previousSnapshot) return;

      const currentMine = knownMyReactions(previousSnapshot);
      const clickedMine = currentMine.includes(emoji);
      const removeOps = clickedMine ? [emoji] : currentMine;
      const addOp = clickedMine ? null : emoji;
      const nextMyReactions = clickedMine ? currentMine.filter((value) => value !== emoji) : [emoji];
      const pendingKey = String(messageId);

      setMessages((current) =>
        withMessageByRawId(current, messageId, (message) => applyOptimisticReactionState(message, nextMyReactions)),
      );
      setReactionPendingByMessageId((current) => ({ ...current, [pendingKey]: emoji }));

      const run = (async () => {
        let committedMyReactions = currentMine;
        try {
          for (const reaction of removeOps) {
            await reactToMessage(messageId, reaction);
            committedMyReactions = committedMyReactions.filter((value) => value !== reaction);
          }
          if (addOp) {
            await reactToMessage(messageId, addOp);
            committedMyReactions = [addOp];
          }
        } catch (error) {
          debugChat("react failed", { messageId, emoji, error });
          setMessages((current) =>
            withMessageByRawId(current, messageId, () => applyOptimisticReactionState(previousSnapshot, committedMyReactions)),
          );
        } finally {
          reactionRequestRef.current.delete(messageId);
          setReactionPendingByMessageId((current) => {
            const next = { ...current };
            delete next[pendingKey];
            return next;
          });
        }
      })();

      reactionRequestRef.current.set(messageId, { emoji, promise: run });
      await run;
    },
    [partnerUserId],
  );

  const deleteChat = useCallback(async () => {
    if (partnerUserId == null || matchId == null) return;
    try {
      await deleteChatByMatchId(matchId);
      emitChatSync({ type: "inboxInvalidate", partnerUserId });
      routerRef.current.replace("/chat");
    } catch (error: unknown) {
      setLoadError(error instanceof Error ? localizeChatMessage(error.message) : i18nKey("chat.thread.errors.deleteChat"));
    }
  }, [partnerUserId, matchId, localizeChatMessage]);

  const ignorePartner = useCallback(async () => {
    if (partnerUserId == null) return;
    try {
      await ignoreUser(partnerUserId);
      setPartner((previous) => (previous ? { ...previous, ignoredByMe: true } : null));
      emitChatSync({ type: "inboxInvalidate", partnerUserId });
    } catch (error: unknown) {
      setSendError(error instanceof Error ? localizeChatMessage(error.message) : i18nKey("chat.thread.errors.ignoreUser"));
    }
  }, [partnerUserId, localizeChatMessage]);

  const unignorePartner = useCallback(async () => {
    if (partnerUserId == null) return;
    try {
      await unignoreUser(partnerUserId);
      setPartner((previous) => (previous ? { ...previous, ignoredByMe: false } : null));
      emitChatSync({ type: "inboxInvalidate", partnerUserId });
    } catch (error: unknown) {
      setSendError(error instanceof Error ? localizeChatMessage(error.message) : i18nKey("chat.thread.errors.unignoreUser"));
    }
  }, [partnerUserId, localizeChatMessage]);

  const loadOlderMessages = useCallback(async () => {
    if (partnerUserId == null || !threadHasMore || olderLoading) return;
    setOlderLoading(true);
    try {
      const offset = messagesRef.current.length;
      const next = await fetchThreadMessages(partnerUserId, "chat-thread-older", { limit: 50, offset });
      if (activeThreadPartnerRef.current !== partnerUserId) return;
      setPartnerLastReadAt(next.partnerLastReadAt);
      setPartnerLastActiveAt(next.partnerLastActiveAt);
      setThreadHasMore(next.threadHasMore);
      const vid = viewerRef.current?.userId ?? null;
      startTransition(() => {
        const older = applyReadReceipts(
          mergeServerWithPendingReactions(next.messages, [], reactionPendingRef.current),
          vid,
          next.partnerLastReadAt,
        );
        const keys = new Set(older.map((m) => messageKey(m)));
        setMessages((current) => {
          const rest = current.filter((m) => !keys.has(messageKey(m)));
          return sortMessages([...older, ...rest]);
        });
      });
    } catch {
      /* non-fatal */
    } finally {
      setOlderLoading(false);
    }
  }, [partnerUserId, threadHasMore, olderLoading]);

  useEffect(() => {
    if (partnerUserId == null) return;
    if (!viewer?.userId) return;
    if (!partner) return;
    if (partner.isDemoProfile) return;
    if (loading) return;
    if (blockedThread) return;
    if (messages.length > 0) return;
    const key = `neyra:ai-opener:${partnerUserId}`;
    if (typeof sessionStorage !== "undefined" && sessionStorage.getItem(key)) return;
    const delayMs = 3000 + Math.floor(Math.random() * 5000);
    const tid = window.setTimeout(() => {
      if (activeThreadPartnerRef.current !== partnerUserId) return;
      if (messagesRef.current.length > 0) return;
      void (async () => {
        setOpenerDrafting(true);
        await new Promise<void>((r) => {
          window.setTimeout(r, 2000 + Math.random() * 2000);
        });
        try {
          await postAiConversationOpener(partnerUserId, getStoredLocale());
          await loadThreadSnapshot(partnerUserId, { manual: true, loadGen: threadLoadGenRef.current });
          if (typeof sessionStorage !== "undefined") sessionStorage.setItem(key, "1");
        } catch {
          /* silent failsafe */
        } finally {
          setOpenerDrafting(false);
        }
      })();
    }, delayMs);
    return () => window.clearTimeout(tid);
  }, [partnerUserId, viewer?.userId, partner?.isDemoProfile, loading, blockedThread, messages.length, loadThreadSnapshot]);

  const blockPartner = useCallback(async () => {
    if (partnerUserId == null || blocking) return;
    setBlocking(true);
    try {
      await blockUser(partnerUserId);
      router.replace("/chat");
    } catch (error: unknown) {
      setLoadError(error instanceof Error ? localizeChatMessage(error.message) : i18nKey("chat.thread.errors.blockUser"));
    } finally {
      setBlocking(false);
    }
  }, [partnerUserId, router, blocking, localizeChatMessage]);

  const reportPartner = useCallback(
    async (category: ReportCategory, details: string) => {
      if (partnerUserId == null) return;
      try {
        await reportUser(partnerUserId, category, details);
        setLoadError(i18nKey("chat.thread.report.received"));
      } catch (error: unknown) {
        setLoadError(error instanceof Error ? localizeChatMessage(error.message) : i18nKey("chat.thread.errors.reportUser"));
      }
    },
    [partnerUserId, localizeChatMessage],
  );

  const canCompose = !blockedThread && !((loading && messages.length === 0) || (Boolean(loadError) && messages.length === 0));

  return {
    partnerUserId,
    viewer,
    partner,
    matchId,
    messages,
    draft,
    setDraft,
    loading,
    refreshing,
    sending,
    loadError,
    sendError,
    blockedThread,
    threadSeed,
    myAvatarUrl,
    myCity,
    replyTo,
    setReplyTo,
    blocking,
    reactionPendingByMessageId,
    displayNameForThread,
    partnerAvatarUrl,
    myName,
    showMessageSkeleton,
    showHeaderSkeleton,
    canCompose,
    isSendingVoice,
    voiceSendPhase,
    voiceSendError,
    partnerTyping,
    partnerLastReadAt,
    partnerLastActiveAt,
    threadHasMore,
    openerDrafting,
    olderLoading,
    actions: {
      send,
      sendMessageNow,
      sendVoice,
      retryVoice,
      retrySend,
      refresh,
      react,
      blockPartner,
      reportPartner,
      deleteChat,
      ignorePartner,
      unignorePartner,
      loadOlderMessages,
    },
  };
}
