import { apiFetch } from "../api";

export type MonetizationEventType =
  | "like_received"
  | "match_created"
  | "message_sent"
  | "message_ignored"
  | "chat_idle"
  | "boost_used"
  | "swipe_limit_reached";

export async function trackUserEvent(eventType: MonetizationEventType, metadata: Record<string, unknown> = {}) {
  try {
    return await apiFetch("/monetization/event", {
      method: "POST",
      metaReason: `monetization:${eventType}`,
      body: JSON.stringify({ eventType, metadata }),
      skipThrottle: true,
      skipCache: true,
    });
  } catch {
    return null;
  }
}

