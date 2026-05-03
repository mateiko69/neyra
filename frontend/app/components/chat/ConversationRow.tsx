"use client";

import Link from "next/link";
import { debugChat } from "../../../lib/chat/debug";
import { setChatThreadHeaderSeed } from "../../../lib/chat/threadHeaderSeed";
import type { ChatConversation } from "../../../lib/chat/types";
import { useT } from "../i18n/I18nProvider";
import { inspectI18nText, renderDebugText } from "../i18n/debugText";
import { ChatAvatar } from "./ChatAvatar";

type ConversationRowProps = {
  conversation: ChatConversation;
};

function formatConversationTimestamp(value: string | null, locale: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;

  const now = new Date();
  const isSameDay = now.toDateString() === date.toDateString();
  if (isSameDay) {
    return date.toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
  }

  const isSameYear = now.getFullYear() === date.getFullYear();
  return date.toLocaleDateString(locale, isSameYear ? { month: "short", day: "numeric" } : { year: "numeric", month: "short", day: "numeric" });
}

export function ConversationRow({ conversation }: ConversationRowProps) {
  const { t, locale } = useT("ConversationRow");
  const preview = conversation.lastMessagePreview || t("chat.list.previewFallback");
  const timestamp = formatConversationTimestamp(conversation.lastMessageAt, locale);
  const unreadLabel = conversation.unreadCount > 9 ? "9+" : String(conversation.unreadCount);
  const avatarAlt = inspectI18nText(t("chat.list.avatarAlt", { name: conversation.partnerName }), {
    component: "ConversationRow",
    prop: "avatarAlt",
  });

  return (
    <Link
      href={`/chat/${conversation.partnerUserId}`}
      prefetch={false}
      className={`chat-inbox-row ${conversation.unreadCount > 0 ? "chat-inbox-row--unread" : ""}`.trim()}
      onClick={() => {
        debugChat("navigate thread from inbox row", {
          partnerUserId: conversation.partnerUserId,
          matchId: conversation.matchId,
        });
        setChatThreadHeaderSeed(conversation.partnerUserId, {
          displayName: conversation.partnerName,
          avatarUrl: conversation.partnerAvatarUrl,
        });
      }}
    >
        <ChatAvatar
          className="chat-avatar chat-avatar--inbox"
          name={conversation.partnerName}
          src={conversation.partnerAvatarUrl}
          alt={avatarAlt.text}
        />

      <div className="chat-inbox-row__body">
        <div className="chat-inbox-row__top">
          <div className="chat-inbox-row__title">
            <span className="chat-inbox-row__name">{conversation.partnerName}</span>
            {conversation.partnerIsDemoProfile ? (
              <span className="chat-inbox-row__demo-badge" title={t("demo.profile.disclaimer_short")}>
                {t("demo.badge")}
              </span>
            ) : null}
          </div>
          {timestamp ? (
            <time className="chat-inbox-row__time" dateTime={conversation.lastMessageAt ?? undefined}>
              {timestamp}
            </time>
          ) : null}
        </div>
        <p className="chat-inbox-row__preview">{renderDebugText(preview, { component: "ConversationRow", prop: "preview", allowRaw: true })}</p>
      </div>

      <div className="chat-inbox-row__aside">
        {conversation.unreadCount > 0 ? <span className="chat-pill">{unreadLabel}</span> : null}
        <span className="chat-inbox-row__open" aria-hidden>
          {renderDebugText(t("chat.list.open"), { component: "ConversationRow", prop: "openLabel" })}
        </span>
      </div>
    </Link>
  );
}
