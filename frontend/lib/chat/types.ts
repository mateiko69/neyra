export const CHAT_REACTION_EMOJIS = ["❤️", "👍", "😂"] as const;
export type ChatReactionEmoji = (typeof CHAT_REACTION_EMOJIS)[number];

export type ChatViewer = {
  userId: number;
  displayName: string;
  email: string;
  isAdmin: boolean;
  isPremium?: boolean;
  premiumUntil?: string | null;
  isTrial?: boolean;
  isTrialUsed?: boolean;
  trialStartedAt?: string | null;
  trialDaysLeft?: number | null;
  /** Optional language prefs (if backend supports). */
  nativeLanguage?: string | null;
  additionalLanguages?: string[];
};

export type ChatMessage = {
  id: string;
  rawId: number | null;
  senderId: number;
  receiverId: number | null;
  /** Optional server hints — used to ensure AI never renders as a participant. */
  role?: "user" | "assistant" | "system" | string;
  aiGenerated?: boolean;
  content: string;
  timestamp: string | null;
  createdAt?: string | null;
  replyToMessageId?: string | null;
  voiceUrl?: string | null;
  voiceMime?: string | null;
  voiceDurationMs?: number | null;
  reactions?: Record<string, number>;
  myReactions?: string[];
  isDeleted?: boolean;
  deletedAt?: string | null;
  isDemoSimulation?: boolean;
  /** Client-only status for optimistic UI (not from API). */
  clientStatus?: "sending" | "sent" | "delivered" | "failed";
  /** Client-only: stable key for retries / replacement. */
  clientTempId?: string;
  /** Derived: partner read thread at or after this outgoing message. */
  readByPartner?: boolean;
};

export type ChatPartnerProfile = {
  userId: number;
  ignoredByMe?: boolean;
  displayName: string;
  age: number | null;
  city: string;
  bio: string;
  interests: string[];
  lifestyleTags: string[];
  relationshipGoal: string;
  photoUrls: string[];
  primaryPhotoUrl: string;
  verified: boolean;
  isDemoProfile?: boolean;
  demoLabel?: string | null;
  demoDisclaimer?: string | null;
  demoChatLabel?: string | null;
  /** Optional language prefs (if backend supports). */
  nativeLanguage?: string | null;
  additionalLanguages?: string[];
};

export type ChatConversation = {
  matchId: number;
  partnerUserId: number;
  partnerName: string;
  partnerAvatarUrl: string | null;
  lastMessagePreview: string;
  lastMessageAt: string | null;
  unreadCount: number;
  partnerIsDemoProfile?: boolean;
  demoLabel?: string | null;
  demoDisclaimer?: string | null;
  demoChatLabel?: string | null;
};

export type ChatSendResult =
  | {
      kind: "sent";
      message: ChatMessage;
      extraMessages?: ChatMessage[];
      demoReplyScheduled?: boolean;
      demoPartner?: boolean;
      expectedReplyDelaySeconds?: number;
    }
  | {
      kind: "rewriteSuggested";
      suggestion: string;
    };
