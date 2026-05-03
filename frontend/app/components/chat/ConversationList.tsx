"use client";

import type { ChatConversation } from "../../../lib/chat/types";
import { useT } from "../i18n/I18nProvider";
import { inspectI18nText } from "../i18n/debugText";
import { ConversationRow } from "./ConversationRow";

type ConversationListProps = {
  conversations: ChatConversation[];
};

export function ConversationList({ conversations }: ConversationListProps) {
  const { t } = useT("ConversationList");
  const ariaLabel = inspectI18nText(t("chat.list.aria"), { component: "ConversationList", prop: "ariaLabel" });

  return (
    <div className="chat-inbox-list" aria-label={ariaLabel.text}>
      {conversations.map((conversation) => (
        <ConversationRow key={`${conversation.partnerUserId}:${conversation.matchId}`} conversation={conversation} />
      ))}
    </div>
  );
}
