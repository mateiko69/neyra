"use client";

import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiUnauthorizedError, AUTH_UNAUTHORIZED_EVENT, isAuthSessionTerminated } from "../api";
import {
  CHAT_INBOX_POLL_MS,
  CHAT_SYNC_EVENT,
  type ChatSyncDetail,
  fetchChatConversations,
  hasChatSession,
} from "./api";
import { debugChat } from "./debug";
import { isBenignChatRequestFailure } from "./errors";
import { i18nKey, type I18nText } from "../i18n/message";
import { apiFailureToI18nText } from "../i18n/translateApiUserMessage";
import type { ChatConversation } from "./types";
import { PAGE_BOOT_FETCH_DELAY_MS, schedulePageLoad } from "../pageLoad";
import { useI18nController } from "../i18n";

function unreadSummary(
  conversations: ChatConversation[],
  t: (key: string, vars?: Record<string, string | number>) => string,
): string | undefined {
  const unreadCount = conversations.reduce((total, conversation) => total + conversation.unreadCount, 0);
  if (unreadCount > 0) return t("chat.inbox.status.unread", { count: unreadCount });
  if (conversations.length === 1) return t("chat.inbox.status.one", { count: conversations.length });
  if (conversations.length > 1) return t("chat.inbox.status.other", { count: conversations.length });
  return undefined;
}

export function useChatInboxController() {
  const router = useRouter();
  const { t } = useI18nController();

  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<I18nText>(null);

  /**
   * Bumps on each inbox mount (incl. React Strict Mode remount). Loads tagged with an old gen are ignored
   * so an aborted first fetch cannot leave the list empty while a second fetch is in flight.
   */
  const inboxEffectGenRef = useRef(0);
  const manualInFlightRef = useRef(false);
  const inboxSyncDebounceRef = useRef<number | null>(null);
  const inboxPollIntervalRef = useRef<number | null>(null);
  const tRef = useRef(t);
  tRef.current = t;

  const runInboxLoad = useCallback(
    async (reason: string, options?: { manual?: boolean; background?: boolean; effectGen?: number }) => {
      const isBackground = Boolean(options?.background);
      const effectGen = options?.effectGen;
      const stale = () => effectGen != null && effectGen !== inboxEffectGenRef.current;

      if (options?.manual) {
        if (manualInFlightRef.current) return;
        manualInFlightRef.current = true;
      }

      if (options?.manual) setRefreshing(true);
      if (!isBackground) setError(null);

      try {
        const nextConversations = await fetchChatConversations(reason);
        if (stale()) {
          debugChat("inbox ignore stale load", { reason, effectGen, currentGen: inboxEffectGenRef.current });
          return;
        }

        if (isBackground) {
          startTransition(() => {
            if (!stale()) setConversations(nextConversations);
          });
        } else {
          setConversations(nextConversations);
        }
      } catch (errorValue) {
        if (errorValue instanceof ApiUnauthorizedError) {
          if (inboxPollIntervalRef.current != null) {
            window.clearInterval(inboxPollIntervalRef.current);
            inboxPollIntervalRef.current = null;
          }
          return;
        }
        if (isBenignChatRequestFailure(errorValue)) return;
        if (stale()) return;
        if (!isBackground) {
          const message = apiFailureToI18nText(errorValue, tRef.current, "chat.inbox.errors.load");
          setError(message);
          setConversations([]);
        }
      } finally {
        if (options?.manual) {
          manualInFlightRef.current = false;
          setRefreshing(false);
        } else if (!isBackground) {
          if (effectGen == null || effectGen === inboxEffectGenRef.current) setLoading(false);
        }
      }
    },
    [],
  );

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const onUnauthorized = () => {
      if (inboxPollIntervalRef.current != null) {
        window.clearInterval(inboxPollIntervalRef.current);
        inboxPollIntervalRef.current = null;
      }
    };
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  useEffect(() => {
    debugChat("inbox mount");
    if (!hasChatSession()) {
      router.replace("/login");
      return;
    }

    inboxEffectGenRef.current += 1;
    const effectGen = inboxEffectGenRef.current;

    const cancelInitialLoad = schedulePageLoad(() => {
      void runInboxLoad("chat-inbox-initial", { effectGen });
    }, PAGE_BOOT_FETCH_DELAY_MS);

    inboxPollIntervalRef.current = window.setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState !== "visible") return;
      if (isAuthSessionTerminated()) return;
      void runInboxLoad("chat-inbox-poll", { background: true, effectGen: inboxEffectGenRef.current });
    }, CHAT_INBOX_POLL_MS);

    const handlePageShow = (event: PageTransitionEvent) => {
      if (!event.persisted) return;
      void runInboxLoad("chat-inbox-pageshow", { background: true, effectGen: inboxEffectGenRef.current });
    };

    const handleChatSync = (event: Event) => {
      const detail = (event as CustomEvent<ChatSyncDetail>).detail;
      if (detail?.type === "threadOpened" && detail?.partnerUserId != null) {
        startTransition(() => {
          setConversations((previous) =>
            previous.map((conversation) =>
              conversation.partnerUserId === detail.partnerUserId ? { ...conversation, unreadCount: 0 } : conversation,
            ),
          );
        });
      }
      if (inboxSyncDebounceRef.current != null) window.clearTimeout(inboxSyncDebounceRef.current);
      inboxSyncDebounceRef.current = window.setTimeout(() => {
        inboxSyncDebounceRef.current = null;
        void runInboxLoad("chat-inbox-sync", { background: true, effectGen: inboxEffectGenRef.current });
      }, 1_500);
    };

    window.addEventListener("pageshow", handlePageShow);
    window.addEventListener(CHAT_SYNC_EVENT, handleChatSync as EventListener);

    return () => {
      cancelInitialLoad();
      if (inboxPollIntervalRef.current != null) {
        clearInterval(inboxPollIntervalRef.current);
        inboxPollIntervalRef.current = null;
      }
      if (inboxSyncDebounceRef.current != null) window.clearTimeout(inboxSyncDebounceRef.current);
      window.removeEventListener("pageshow", handlePageShow);
      window.removeEventListener(CHAT_SYNC_EVENT, handleChatSync as EventListener);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runInboxLoad is stable by design
  }, []);

  const status = useMemo(() => (loading ? undefined : unreadSummary(conversations, t)), [loading, conversations, t]);

  return {
    conversations,
    loading,
    refreshing,
    error,
    status,
    refresh: useCallback(() => runInboxLoad("chat-inbox-manual", { manual: true }), [runInboxLoad]),
    retry: useCallback(() => runInboxLoad("chat-inbox-retry", { manual: true }), [runInboxLoad]),
  };
}
