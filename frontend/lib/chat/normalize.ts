import { primaryPhotoFromList, resolveMediaUrl } from "../media";
import { resolveDemoProfilePhoto } from "../resolvePhoto";
import type { ChatConversation, ChatMessage, ChatPartnerProfile, ChatSendResult, ChatViewer } from "./types";

function toNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return Math.trunc(value);
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return Math.trunc(parsed);
  }
  return null;
}

function toText(value: unknown): string {
  if (value == null) return "";
  return String(value).trim();
}

function toTextArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((entry) => {
        if (entry == null) return "";
        if (typeof entry === "string") return entry.trim();
        if (typeof entry === "object" && entry !== null && "name" in entry) {
          return toText((entry as { name?: unknown }).name);
        }
        return toText(entry);
      })
      .filter(Boolean);
  }
  if (typeof value === "string") {
    return value
      .split(",")
      .map((entry) => entry.trim())
      .filter(Boolean);
  }
  return [];
}

function toTimestamp(value: unknown): string | null {
  const text = toText(value);
  return text || null;
}

function toBoolean(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (!normalized) return false;
    return normalized === "true" || normalized === "1" || normalized === "yes";
  }
  return false;
}

function nestedNumber(object: Record<string, unknown>, key: string): number | null {
  const candidate = object[key];
  if (candidate == null || typeof candidate !== "object") return null;
  return toNumber((candidate as Record<string, unknown>).id);
}

function nestedText(object: Record<string, unknown>, key: string, nestedKey: string): string {
  const candidate = object[key];
  if (candidate == null || typeof candidate !== "object") return "";
  return toText((candidate as Record<string, unknown>)[nestedKey]);
}

function normalizePhotoUrls(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((entry) => {
        if (typeof entry === "string") return entry.trim();
        if (entry != null && typeof entry === "object") {
          const item = entry as Record<string, unknown>;
          return toText(item.url ?? item.photo_url ?? item.src);
        }
        return toText(entry);
      })
      .filter(Boolean);
  }

  if (typeof value === "string") {
    return value
      .split(",")
      .map((entry) => entry.trim())
      .filter(Boolean);
  }

  return [];
}

function normalizeMessageCandidate(raw: unknown): Record<string, unknown> | null {
  if (raw == null || typeof raw !== "object") return null;
  return raw as Record<string, unknown>;
}

function normalizeReactionCounts(value: unknown): Record<string, number> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const counts = Object.entries(value as Record<string, unknown>).reduce<Record<string, number>>((acc, [emoji, count]) => {
    const normalizedEmoji = String(emoji || "").trim();
    const normalizedCount = toNumber(count);
    if (!normalizedEmoji || normalizedCount == null || normalizedCount <= 0) return acc;
    acc[normalizedEmoji] = normalizedCount;
    return acc;
  }, {});
  return Object.keys(counts).length > 0 ? counts : undefined;
}

function normalizeMyReactions(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const reactions = Array.from(
    new Set(
      value
        .map((entry) => String(entry ?? "").trim())
        .filter(Boolean),
    ),
  );
  return reactions.length > 0 ? reactions : undefined;
}

function messageSortValue(message: ChatMessage): number {
  if (!message.timestamp) return Number.POSITIVE_INFINITY;
  const parsed = Date.parse(message.timestamp);
  return Number.isFinite(parsed) ? parsed : Number.POSITIVE_INFINITY;
}

export function messageKey(message: ChatMessage): string {
  const reactionKey = Object.entries(message.reactions ?? {})
    .filter(([, count]) => Number.isFinite(count) && count > 0)
    .sort(([leftEmoji], [rightEmoji]) => leftEmoji.localeCompare(rightEmoji))
    .map(([emoji, count]) => `${emoji}:${count}`)
    .join("|");
  const myReactionKey = [...(message.myReactions ?? [])]
    .map((emoji) => String(emoji))
    .filter(Boolean)
    .sort((left, right) => left.localeCompare(right))
    .join("|");

  return [
    message.id,
    message.rawId ?? "raw:x",
    message.senderId,
    message.receiverId ?? "x",
    message.createdAt ?? message.timestamp ?? "",
    message.content,
    message.replyToMessageId ?? "",
    message.voiceUrl ?? "",
    message.voiceMime ?? "",
    message.voiceDurationMs ?? "",
    message.isDeleted ? "deleted" : "active",
    message.deletedAt ?? "",
    message.clientStatus ?? "",
    message.clientTempId ?? "",
    message.isDemoSimulation ? "demo" : "real",
    reactionKey,
    myReactionKey,
  ].join(":");
}

export function sortMessages(messages: ChatMessage[]): ChatMessage[] {
  return [...messages].sort((left, right) => {
    const leftTime = messageSortValue(left);
    const rightTime = messageSortValue(right);
    if (leftTime !== rightTime) return leftTime - rightTime;
    if (left.timestamp !== right.timestamp) return (left.timestamp ?? "").localeCompare(right.timestamp ?? "");
    return left.id.localeCompare(right.id);
  });
}

export function appendThreadMessage(messages: ChatMessage[], nextMessage: ChatMessage): ChatMessage[] {
  if (nextMessage.rawId != null) {
    const dupIdx = messages.findIndex((m) => m.rawId === nextMessage.rawId);
    if (dupIdx !== -1) {
      const next = [...messages];
      next[dupIdx] = { ...messages[dupIdx], ...nextMessage };
      return sortMessages(next);
    }
  }
  const existing = new Set(messages.map(messageKey));
  if (existing.has(messageKey(nextMessage))) return messages;
  return sortMessages([...messages, nextMessage]);
}

export function messagesSnapshotEqual(left: ChatMessage[], right: ChatMessage[]): boolean {
  if (left.length !== right.length) return false;
  for (let index = 0; index < left.length; index += 1) {
    if (messageKey(left[index]) !== messageKey(right[index])) return false;
  }
  return true;
}

export function conversationContext(messages: ChatMessage[], limit: number = 10): string[] {
  return messages
    .slice(-limit)
    .map((message) => message.content.trim())
    .filter(Boolean);
}

export function normalizeChatViewer(raw: unknown): ChatViewer | null {
  const object = normalizeMessageCandidate(raw);
  if (!object) return null;

  const userId = toNumber(object.user_id ?? object.userId ?? object.id);
  if (userId == null || userId < 1) return null;

  return {
    userId,
    displayName: toText(object.display_name ?? object.displayName) || "",
    email: toText(object.email),
    isAdmin: Boolean(object.is_admin ?? object.isAdmin),
    isPremium: Boolean(object.is_premium ?? object.isPremium),
    premiumUntil: toTimestamp(object.premium_until ?? object.premiumUntil),
    isTrial: toBoolean(object.is_trial ?? object.isTrial),
    isTrialUsed: toBoolean(object.is_trial_used ?? object.isTrialUsed),
    trialStartedAt: toTimestamp(object.trial_started_at ?? object.trialStartedAt),
    trialDaysLeft: toNumber(object.trial_days_left ?? object.trialDaysLeft),
    nativeLanguage: toText(object.native_language ?? (object as any).nativeLanguage) || null,
    additionalLanguages: toTextArray(object.additional_languages ?? (object as any).additionalLanguages),
  };
}

export function normalizeChatMessage(raw: unknown): ChatMessage | null {
  const object = normalizeMessageCandidate(raw);
  if (!object) return null;

  const roleRaw = toText((object as any).role) || toText((object as any).sender_role) || toText((object as any).senderRole);
  const role = roleRaw ? roleRaw.trim().toLowerCase() : "";
  const aiGenerated = toBoolean((object as any).ai_generated ?? (object as any).aiGenerated ?? (object as any).generated_by_ai ?? (object as any).generatedByAi);

  const senderId =
    toNumber(object.sender_id ?? object.senderId ?? object.from_user_id ?? object.fromUserId) ??
    nestedNumber(object, "sender") ??
    nestedNumber(object, "from");
  const receiverId =
    toNumber(object.receiver_id ?? object.receiverId ?? object.to_user_id ?? object.toUserId) ??
    nestedNumber(object, "receiver") ??
    nestedNumber(object, "to");
  const content =
    toText(object.content) ||
    toText(object.text) ||
    toText(object.body) ||
    toText(object.message);
  const voiceUrlRaw = toText(object.voice_url ?? object.voiceUrl) || "";
  const voiceUrl = voiceUrlRaw ? resolveMediaUrl(voiceUrlRaw) : "";
  const voiceMime = toText(object.voice_mime ?? object.voiceMime) || "";
  const voiceDurationMs = toNumber(object.voice_duration_ms ?? object.voiceDurationMs);
  const rawId = toNumber(object.id ?? object.message_id ?? object.messageId);
  const timestamp =
    toTimestamp(object.created_at ?? object.createdAt ?? object.timestamp ?? object.sent_at ?? object.sentAt);
  const replyToRaw = toNumber(object.reply_to_message_id ?? object.replyToMessageId ?? object.reply_to ?? object.replyTo);
  const isDeleted = toBoolean(object.is_deleted ?? object.isDeleted ?? object.deleted);
  const deletedAt = toTimestamp(object.deleted_at ?? object.deletedAt);
  const reactions = normalizeReactionCounts(object.reactions);
  const myReactions = normalizeMyReactions(object.my_reactions ?? object.myReactions);
  const isDemoSimulation = toBoolean(
    object.is_demo_simulation ?? object.isDemoSimulation ?? object.demo_simulation ?? object.is_demo ?? object.isDemo,
  );

  if (senderId == null) return null;
  if (!content && !voiceUrl && !isDeleted) return null;

  const fallbackId = [
    senderId,
    receiverId ?? "x",
    timestamp ?? "untimed",
    isDeleted ? "deleted" : voiceUrl ? "voice" : content.slice(0, 48),
  ].join(":");

  return {
    id: rawId != null ? String(rawId) : fallbackId,
    rawId,
    senderId,
    receiverId,
    role: role || undefined,
    aiGenerated: aiGenerated ? true : undefined,
    content,
    timestamp,
    createdAt: timestamp,
    replyToMessageId: replyToRaw != null ? String(replyToRaw) : null,
    voiceUrl: voiceUrl || null,
    voiceMime: voiceMime || null,
    voiceDurationMs: voiceDurationMs != null && voiceDurationMs >= 0 ? voiceDurationMs : null,
    reactions,
    myReactions,
    isDeleted,
    deletedAt,
    isDemoSimulation,
  };
}

export function normalizeThreadPayload(raw: unknown): ChatMessage[] {
  if (raw == null) return [];

  let rows: unknown[] = [];
  if (Array.isArray(raw)) {
    rows = raw;
  } else if (typeof raw === "object") {
    const object = raw as Record<string, unknown>;
    const nested = object.items ?? object.messages ?? object.data ?? object.results ?? object.thread ?? object.conversation;
    if (Array.isArray(nested)) rows = nested;
  }

  return sortMessages(
    rows
      .map(normalizeChatMessage)
      .filter((message): message is ChatMessage => message != null),
  );
}

export function normalizeThreadFetch(raw: unknown): {
  messages: ChatMessage[];
  matchId: number | null;
  partnerLastReadAt: string | null;
  partnerLastActiveAt: string | null;
  threadHasMore: boolean;
} {
  let matchId: number | null = null;
  let partnerLastReadAt: string | null = null;
  let partnerLastActiveAt: string | null = null;
  let threadHasMore = false;
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const object = raw as Record<string, unknown>;
    const mid = toNumber(object.match_id ?? object.matchId);
    matchId = mid != null && mid >= 1 ? mid : null;
    partnerLastReadAt = toTimestamp(object.partner_last_read_at ?? object.partnerLastReadAt);
    partnerLastActiveAt = toTimestamp(object.partner_last_active_at ?? object.partnerLastActiveAt);
    threadHasMore = toBoolean(object.thread_has_more ?? object.threadHasMore);
  }
  return {
    messages: normalizeThreadPayload(raw),
    matchId,
    partnerLastReadAt,
    partnerLastActiveAt,
    threadHasMore,
  };
}

export function normalizePartnerProfile(raw: unknown): ChatPartnerProfile | null {
  const object = normalizeMessageCandidate(raw);
  if (!object) return null;

  const userId = toNumber(object.user_id ?? object.userId ?? object.id);
  if (userId == null || userId < 1) return null;

  const photoUrls = normalizePhotoUrls(object.photo_urls ?? object.photoUrls ?? object.photos);
  const primaryPhoto = toText(
    object.primary_photo ??
      object.primaryPhoto ??
      object.photo_url ??
      object.photoUrl ??
      object.avatar_url ??
      object.avatarUrl ??
      object.demo_profile_photo_url ??
      object.demoProfilePhotoUrl ??
      object.demo_photo_url ??
      object.demoPhotoUrl,
  );
  const resolvedPhotoUrls = photoUrls.length > 0 ? photoUrls : primaryPhoto ? [primaryPhoto] : [];
  const primaryResolved = resolveDemoProfilePhoto({
    ...object,
    photo_urls: resolvedPhotoUrls,
    primary_photo_url: primaryPhoto,
  });

  return {
    userId,
    ignoredByMe: toBoolean(object.ignored_by_me ?? object.ignoredByMe),
    displayName: toText(object.display_name ?? object.displayName ?? object.name) || "Conversation",
    age: toNumber(object.age),
    city: toText(object.city),
    bio: toText(object.bio),
    interests: toTextArray(object.interests),
    lifestyleTags: toTextArray(object.lifestyle_tags ?? object.lifestyleTags),
    relationshipGoal: toText(object.relationship_goal ?? object.relationshipGoal) || "relationship",
    photoUrls: resolvedPhotoUrls,
    primaryPhotoUrl: primaryResolved || primaryPhotoFromList(resolvedPhotoUrls),
    verified: Boolean(object.verified ?? object.is_verified ?? object.isVerified),
    isDemoProfile: toBoolean(object.is_demo_profile ?? object.isDemoProfile ?? object.partner_is_demo_profile ?? object.partnerIsDemoProfile),
    demoLabel: toText(object.demo_label ?? object.demoLabel) || null,
    demoDisclaimer: toText(object.demo_disclaimer ?? object.demoDisclaimer) || null,
    demoChatLabel: toText(object.demo_chat_label ?? object.demoChatLabel) || null,
    nativeLanguage: toText(object.native_language ?? (object as any).nativeLanguage) || null,
    additionalLanguages: toTextArray(object.additional_languages ?? (object as any).additionalLanguages),
  };
}

function avatarFromConversationObject(object: Record<string, unknown>): string | null {
  const directAvatar = toText(
    object.partner_photo ??
      object.partnerPhoto ??
      object.avatar_url ??
      object.avatarUrl ??
      object.partner_photo_url ??
      object.partnerPhotoUrl ??
      object.demo_profile_photo_url ??
      object.demoProfilePhotoUrl,
  );
  if (directAvatar) {
    return resolveDemoProfilePhoto({
      ...object,
      partner_photo: directAvatar,
      photo_url: directAvatar,
      avatar_url: directAvatar,
    });
  }

  const nestedProfile = object.partner_profile ?? object.partnerProfile ?? object.profile;
  if (nestedProfile && typeof nestedProfile === "object") {
    const profileObject = nestedProfile as Record<string, unknown>;
    const photoUrls = normalizePhotoUrls(
      profileObject.photo_urls ?? profileObject.photoUrls ?? profileObject.photos ?? profileObject.primary_photo,
    );
    return (
      resolveDemoProfilePhoto({
        ...profileObject,
        photo_urls: photoUrls,
      }) ||
      primaryPhotoFromList(photoUrls) ||
      null
    );
  }

  return null;
}

export function normalizeConversationRow(raw: unknown): ChatConversation | null {
  const object = normalizeMessageCandidate(raw);
  if (!object) return null;

  const partnerUserId = toNumber(
    object.partner_user_id ??
      object.partnerUserId ??
      object.partner_id ??
      object.partnerId ??
      object.other_user_id ??
      object.otherUserId ??
      object.peer_user_id ??
      object.peerUserId ??
      object.counterpart_user_id ??
      object.counterpartUserId,
  );
  if (partnerUserId == null || partnerUserId < 1) return null;

  const matchId = toNumber(object.match_id ?? object.matchId) ?? partnerUserId;
  const lastMessagePreview =
    toText(object.last_message_preview ?? object.lastMessagePreview ?? object.last_message_text ?? object.lastMessageText) ||
    toText(object.preview ?? object.snippet) ||
    nestedText(object, "last_message", "content");
  const lastMessageAt = toTimestamp(
    object.last_message_at ??
      object.lastMessageAt ??
      object.last_message_time ??
      object.lastMessageTime ??
      object.updated_at ??
      object.updatedAt,
  );
  const unreadCount = Math.max(
    0,
    toNumber(object.unread_count ?? object.unreadCount ?? object.unread_messages ?? object.unreadMessages) ?? 0,
  );

  const partnerNameRaw = toText(
    object.partner_display_name ??
      object.partnerDisplayName ??
      nestedText(object, "partner_profile", "display_name") ??
      nestedText(object, "partnerProfile", "display_name") ??
      nestedText(object, "partner", "display_name"),
  );
  return {
    matchId,
    partnerUserId,
    partnerName: partnerNameRaw || "Unknown",
    partnerAvatarUrl: avatarFromConversationObject(object),
    lastMessagePreview,
    lastMessageAt,
    unreadCount,
    partnerIsDemoProfile: toBoolean(object.partner_is_demo_profile ?? object.partnerIsDemoProfile ?? object.is_demo_profile ?? object.isDemoProfile),
    demoLabel: toText(object.demo_label ?? object.demoLabel) || null,
    demoDisclaimer: toText(object.demo_disclaimer ?? object.demoDisclaimer) || null,
    demoChatLabel: toText(object.demo_chat_label ?? object.demoChatLabel) || null,
  };
}

export function normalizeConversationsPayload(raw: unknown): ChatConversation[] {
  if (raw == null) return [];

  let rows: unknown[] = [];
  if (Array.isArray(raw)) {
    rows = raw;
  } else if (typeof raw === "object") {
    const object = raw as Record<string, unknown>;
    const nested =
      object.items ??
      object.conversations ??
      object.chats ??
      object.threads ??
      object.rows ??
      object.list ??
      object.results ??
      object.data ??
      object.payload;
    if (Array.isArray(nested)) {
      rows = nested;
    } else if (nested && typeof nested === "object" && !Array.isArray(nested)) {
      const inner = nested as Record<string, unknown>;
      const innerList =
        inner.items ??
        inner.conversations ??
        inner.chats ??
        inner.data ??
        inner.results;
      if (Array.isArray(innerList)) rows = innerList;
    }
  }

  return rows
    .map(normalizeConversationRow)
    .filter((conversation): conversation is ChatConversation => conversation != null)
    .sort((left, right) => {
      const leftTime = left.lastMessageAt ? Date.parse(left.lastMessageAt) : Number.NEGATIVE_INFINITY;
      const rightTime = right.lastMessageAt ? Date.parse(right.lastMessageAt) : Number.NEGATIVE_INFINITY;
      if (leftTime !== rightTime) return rightTime - leftTime;
      return right.unreadCount - left.unreadCount;
    });
}

export function normalizeSendMessageResponse(raw: unknown): ChatSendResult | null {
  const object = normalizeMessageCandidate(raw);
  if (!object) return null;

  if (toText(object.status).toLowerCase() === "rewrite_suggested") {
    return {
      kind: "rewriteSuggested",
      suggestion: toText(object.rewrite_suggestion ?? object.rewriteSuggestion) || "Try softening the message and send again.",
    };
  }

  const message =
    normalizeChatMessage(object.message ?? object.data ?? object.item ?? raw) ??
    normalizeChatMessage(raw);

  if (!message) return null;

  const extraMessages = [
    normalizeChatMessage(object.demo_reply ?? object.demoReply),
    ...(Array.isArray(object.extra_messages ?? object.extraMessages)
      ? ((object.extra_messages ?? object.extraMessages) as unknown[]).map(normalizeChatMessage)
      : []),
  ].filter((item): item is ChatMessage => item != null);

  return {
    kind: "sent",
    message,
    extraMessages: extraMessages.length ? extraMessages : undefined,
    demoReplyScheduled: toBoolean(object.demo_reply_scheduled ?? object.demoReplyScheduled),
    demoPartner: toBoolean(object.demo_partner ?? object.demoPartner),
    expectedReplyDelaySeconds: toNumber(object.expected_reply_delay_seconds ?? object.expectedReplyDelaySeconds) ?? undefined,
  };
}
