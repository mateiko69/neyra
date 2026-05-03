import type { DatingConversationMode } from "./api";

/** Map backend conversation_mode hint → strategist chip id. */
export function mapApiConversationModeToDatingMode(raw: string): DatingConversationMode | null {
  const s = String(raw || "").trim().toLowerCase();
  const mapping: Record<string, DatingConversationMode> = {
    easy: "easy",
    flirty: "flirty",
    playful: "playful",
    deep: "deep",
    confident: "confident",
    romantic: "romantic",
    witty: "funny",
    premium_pickup_master: "pickup_master",
  };
  return mapping[s] ?? null;
}
