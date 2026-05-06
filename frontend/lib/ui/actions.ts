import type { Locale } from "../i18n";

export type UiActionId =
  | "discover.pass"
  | "discover.like"
  | "discover.ignore"
  | "discover.boost"
  | "discover.undo"
  | "chat.getSuggestions"
  | "chat.insertSuggestion"
  | "chat.ignoreProfile"
  | "chat.deleteMessage"
  | "chat.report"
  | "chat.viewProfile"
  | "chat.refresh"
  | "chat.more"
  | "chat.allConversations"
  | "chat.matches"
  | "chat.reply"
  | "chat.react"
  | "chat.send"
  | "chat.ai";

type ActionDef = {
  id: UiActionId;
  i18nKey: string;
  fallbackLabelEn: string;
};

const ACTIONS: Record<UiActionId, ActionDef> = {
  "discover.pass": { id: "discover.pass", i18nKey: "discover.actions.pass", fallbackLabelEn: "Pass" },
  "discover.like": { id: "discover.like", i18nKey: "discover.actions.like", fallbackLabelEn: "Like" },
  "discover.ignore": { id: "discover.ignore", i18nKey: "discover.actions.ignore", fallbackLabelEn: "Ignore" },
  "discover.boost": { id: "discover.boost", i18nKey: "discover.actions.boostProfile", fallbackLabelEn: "Boost profile" },
  "discover.undo": { id: "discover.undo", i18nKey: "discover.actions.undo", fallbackLabelEn: "Undo" },
  "chat.getSuggestions": { id: "chat.getSuggestions", i18nKey: "chat.actions.getSuggestions", fallbackLabelEn: "Get suggestions" },
  "chat.insertSuggestion": { id: "chat.insertSuggestion", i18nKey: "chat.suggestions.inserted", fallbackLabelEn: "Suggestion inserted" },
  "chat.ignoreProfile": { id: "chat.ignoreProfile", i18nKey: "chat.actions.ignoreProfile", fallbackLabelEn: "Ignore profile" },
  "chat.deleteMessage": { id: "chat.deleteMessage", i18nKey: "chat.actions.deleteMessage", fallbackLabelEn: "Delete message" },
  "chat.report": { id: "chat.report", i18nKey: "chat.actions.report", fallbackLabelEn: "Report" },
  "chat.viewProfile": { id: "chat.viewProfile", i18nKey: "chat.actions.viewProfile", fallbackLabelEn: "View profile" },
  "chat.refresh": { id: "chat.refresh", i18nKey: "chat.actions.refresh", fallbackLabelEn: "Refresh" },
  "chat.more": { id: "chat.more", i18nKey: "chat.actions.more", fallbackLabelEn: "More" },
  "chat.allConversations": {
    id: "chat.allConversations",
    i18nKey: "chat.filters.allConversations",
    fallbackLabelEn: "All conversations",
  },
  "chat.matches": { id: "chat.matches", i18nKey: "chat.filters.matches", fallbackLabelEn: "Matches" },
  "chat.reply": { id: "chat.reply", i18nKey: "chat.actions.reply", fallbackLabelEn: "Reply" },
  "chat.react": { id: "chat.react", i18nKey: "chat.actions.react", fallbackLabelEn: "React" },
  "chat.send": { id: "chat.send", i18nKey: "chat.actions.send", fallbackLabelEn: "Send" },
  "chat.ai": { id: "chat.ai", i18nKey: "chat.actions.ai", fallbackLabelEn: "AI" },
};

const warned = new Set<string>();

export function getActionLabel(
  actionId: UiActionId,
  locale: Locale | string,
  t: (key: string, vars?: Record<string, string | number>) => string,
): string {
  const def = ACTIONS[actionId];
  const raw = String(t(def.i18nKey) || "").trim();
  if (raw && raw !== def.i18nKey) return raw;
  const warningKey = `${String(locale)}:${actionId}`;
  if (!warned.has(warningKey)) {
    warned.add(warningKey);
    console.warn(`[neyra:actions] missing label "${def.i18nKey}" for locale "${locale}" (action "${actionId}")`);
  }
  return def.fallbackLabelEn;
}

