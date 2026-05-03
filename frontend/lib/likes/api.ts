import { apiFetch } from "../api";

export type LikesPreviewLevel = "blur" | "partial" | "visible";

export type IncomingLikeItem = {
  user_id: number;
  photo_url: string | null;
  distance: number | null;
  preview_name: string;
};

export type LikesIncomingResponse = {
  waiting_count: number;
  today_count: number;
  is_premium: boolean;
  viewer_is_verified?: boolean;
  items: IncomingLikeItem[];
};

export async function fetchLikesIncoming(options: { limit?: number } = {}): Promise<LikesIncomingResponse> {
  const limit = options.limit != null ? Math.max(1, Math.min(48, Math.trunc(Number(options.limit)))) : 24;
  const res = await apiFetch("/likes/incoming?limit=" + encodeURIComponent(String(limit)), {
    metaReason: "likes-incoming",
    skipThrottle: false,
    skipCache: false,
  });
  const obj = res && typeof res === "object" ? (res as Record<string, unknown>) : {};
  const rawItems = Array.isArray(obj.items) ? obj.items : [];
  const items: IncomingLikeItem[] = rawItems
    .map((r: Record<string, unknown>) => ({
      user_id: Math.max(0, Math.trunc(Number(r?.user_id ?? 0))),
      photo_url: r?.photo_url != null && String(r.photo_url).trim() ? String(r.photo_url) : null,
      distance: r?.distance != null && Number.isFinite(Number(r.distance)) ? Math.max(0, Math.trunc(Number(r.distance))) : null,
      preview_name: String(r?.preview_name ?? "").trim() || "S****",
    }))
    .filter((r: IncomingLikeItem) => r.user_id > 0);
  return {
    waiting_count: Number.isFinite(Number(obj.waiting_count)) ? Math.max(0, Math.trunc(Number(obj.waiting_count))) : items.length,
    today_count: Number.isFinite(Number(obj.today_count)) ? Math.max(0, Math.trunc(Number(obj.today_count))) : 0,
    is_premium: Boolean(obj.is_premium),
    viewer_is_verified: Boolean((obj as { viewer_is_verified?: unknown }).viewer_is_verified),
    items,
  };
}

export async function hideIncomingLike(userId: number): Promise<void> {
  await apiFetch("/likes/hide", {
    method: "POST",
    body: JSON.stringify({ user_id: Math.trunc(Number(userId)) }),
    metaReason: "likes-hide",
    skipThrottle: true,
    skipCache: true,
  });
}

export type LikesRevealResult = {
  ok: boolean;
  requires_premium?: boolean;
  profile_path?: string | null;
};

export async function revealIncomingLike(userId: number): Promise<LikesRevealResult> {
  const res = await apiFetch("/likes/reveal", {
    method: "POST",
    body: JSON.stringify({ user_id: Math.trunc(Number(userId)) }),
    metaReason: "likes-reveal",
    skipThrottle: true,
    skipCache: true,
  });
  const obj = res && typeof res === "object" ? (res as Record<string, unknown>) : {};
  return {
    ok: Boolean(obj.ok),
    requires_premium: Boolean(obj.requires_premium),
    profile_path: obj.profile_path != null ? String(obj.profile_path) : null,
  };
}

export type LikesRespondResult = {
  ok: boolean;
  matched: boolean;
  match_id?: number | null;
  conversation_id?: number | null;
  chat_url?: string | null;
  message?: string | null;
};

export async function respondToIncomingLike(
  userId: number,
  action: "like" | "pass",
): Promise<LikesRespondResult> {
  const res = await apiFetch("/likes/respond", {
    method: "POST",
    body: JSON.stringify({ user_id: Math.trunc(Number(userId)), action }),
    metaReason: "likes-respond",
    skipThrottle: true,
    skipCache: true,
  });
  const obj = res && typeof res === "object" ? (res as Record<string, unknown>) : {};
  const matchIdRaw = obj.match_id;
  const matchId = matchIdRaw != null && Number.isFinite(Number(matchIdRaw)) ? Math.trunc(Number(matchIdRaw)) : null;
  const convoIdRaw = obj.conversation_id;
  const convoId =
    convoIdRaw != null && Number.isFinite(Number(convoIdRaw)) ? Math.trunc(Number(convoIdRaw)) : null;
  return {
    ok: Boolean(obj.ok),
    matched: Boolean(obj.matched),
    match_id: matchId,
    conversation_id: convoId,
    chat_url: obj.chat_url != null ? String(obj.chat_url) : null,
    message: obj.message != null ? String(obj.message) : null,
  };
}

export type LikeReceivedRow = {
  userId: string;
  displayName?: string;
  age: number | null;
  city: string;
  distanceKm: number | null;
  matchScore: number;
  previewLevel: LikesPreviewLevel;
  hasPhoto: boolean;
  photoUrl?: string | null;
  hintKey?: string | null;
};

export type LikesReceivedResponse = {
  count: number;
  likesReceived: LikeReceivedRow[];
};

export async function fetchLikesReceived(options: { limit?: number } = {}): Promise<LikesReceivedResponse> {
  const limit = options.limit != null ? Math.max(1, Math.min(12, Math.trunc(Number(options.limit)))) : 6;
  const res = await apiFetch("/likes/received?limit=" + encodeURIComponent(String(limit)), {
    metaReason: "likes-received",
    skipThrottle: false,
    skipCache: false,
  });
  const obj = res && typeof res === "object" ? (res as any) : {};
  const rows = Array.isArray(obj.likesReceived) ? obj.likesReceived : [];
  return {
    count: Number.isFinite(Number(obj.count)) ? Math.max(0, Math.trunc(Number(obj.count))) : rows.length,
    likesReceived: rows
      .map((r: any) => ({
        userId: String(r?.userId ?? "").trim(),
        displayName: String(r?.displayName ?? "").trim(),
        age: r?.age != null && Number.isFinite(Number(r.age)) ? Math.max(0, Math.trunc(Number(r.age))) : null,
        city: String(r?.city ?? "").trim(),
        distanceKm: r?.distanceKm != null && Number.isFinite(Number(r.distanceKm)) ? Math.max(0, Math.trunc(Number(r.distanceKm))) : null,
        matchScore: Number.isFinite(Number(r?.matchScore)) ? Math.max(0, Math.min(100, Math.trunc(Number(r.matchScore)))) : 0,
        previewLevel: (String(r?.previewLevel ?? "blur") as LikesPreviewLevel) === "visible" ? "visible" : (String(r?.previewLevel ?? "blur") as LikesPreviewLevel) === "partial" ? "partial" : "blur",
        hasPhoto: Boolean(r?.hasPhoto),
        photoUrl: r?.photoUrl ? String(r.photoUrl) : null,
        hintKey: r?.hintKey ? String(r.hintKey) : null,
      }))
      .filter((r: LikeReceivedRow) => Boolean(r.userId))
      .slice(0, limit),
  };
}

