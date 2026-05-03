"use client";

import Link from "next/link";
import { useChatInboxController } from "../../../lib/chat/useChatInboxController";
import { isRawI18nText, resolveI18nText } from "../../../lib/i18n/message";
import { ChatEmptyState } from "./ChatEmptyState";
import { ConversationList } from "./ConversationList";
import { PageHeader } from "../PageHeader";
import { PageShell } from "../PageShell";
import { renderDebugText } from "../i18n/debugText";
import { Button, Skeleton } from "../ui";
import { useT } from "../i18n/I18nProvider";

function InboxSkeleton() {
  return (
    <div className="chat-inbox-list" aria-busy>
      {[0, 1, 2, 3].map((index) => (
        <div key={index} className="chat-inbox-row chat-inbox-row--loading">
          <Skeleton style={{ width: 56, height: 56, borderRadius: 18, flexShrink: 0 }} />
          <div className="chat-inbox-row__body">
            <Skeleton style={{ width: "46%", height: 16, borderRadius: 999 }} />
            <Skeleton style={{ width: "88%", height: 13, borderRadius: 999, marginTop: 10 }} />
          </div>
          <div className="chat-inbox-row__aside">
            <Skeleton style={{ width: 32, height: 20, borderRadius: 999 }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ChatInboxPage() {
  const { t } = useT("ChatInboxPage");
  const { conversations, loading, refreshing, error, status, refresh, retry } = useChatInboxController();
  const errorText = resolveI18nText(error, t);

  return (
    <PageShell className="chat-page-shell">
      <PageHeader
        title={t("chat.inbox.title")}
        subtitle={t("chat.inbox.subtitle")}
        status={status}
        statusVariant="neutral"
        action={
          <>
            <Button type="button" variant="ghost" onClick={refresh} disabled={loading || refreshing}>
              {refreshing ? t("common.refreshing") : t("chat.common.refresh")}
            </Button>
            <Link href="/matches" className="btn btn-secondary">
              {renderDebugText(t("navigation.matches"), { component: "ChatInboxPage", prop: "openMatchesLink" })}
            </Link>
          </>
        }
      />

      <section className="chat-module chat-inbox-module">
        {loading ? <InboxSkeleton /> : null}

        {!loading && error ? (
          <ChatEmptyState title={t("chat.inbox.error.title")} description={errorText} allowRawDescription={isRawI18nText(error)}>
            <Button type="button" variant="primary" onClick={retry}>
              {t("common.tryAgain")}
            </Button>
          </ChatEmptyState>
        ) : null}

        {!loading && !error && conversations.length === 0 ? (
          <ChatEmptyState kicker={t("chat.empty.hook")} title={t("chat.empty")} description={t("chat.empty.subtitle")}>
            <Link href="/matches" className="btn btn-primary">
              {renderDebugText(t("chat.inbox.empty.openMatches"), { component: "ChatInboxPage", prop: "emptyMatchesLink" })}
            </Link>
            <Link href="/discover" className="btn btn-ghost">
              {renderDebugText(t("chat.inbox.empty.discover"), { component: "ChatInboxPage", prop: "emptyDiscoverLink" })}
            </Link>
          </ChatEmptyState>
        ) : null}

        {!loading && !error && conversations.length > 0 ? <ConversationList conversations={conversations} /> : null}
      </section>
    </PageShell>
  );
}
