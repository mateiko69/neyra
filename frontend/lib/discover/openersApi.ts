import { apiFetch } from "../api";
import { getAiLocalePayload } from "../i18n";

export type DiscoverOpenerItem = { type: string; text: string };

export async function fetchDiscoverOpenerSuggestions(input: {
  matchName: string;
  bio?: string;
  interests?: string[];
  city?: string;
  tags?: string[];
  locale: string;
  /** Bump to bypass cache and get a fresh trio. */
  refreshNonce?: number;
}): Promise<{ items: DiscoverOpenerItem[]; suggestions: string[] }> {
  const name = String(input.matchName || "").trim() || "there";
  const conversation_context =
    input.refreshNonce != null && input.refreshNonce > 0 ? [`discover_inline:${input.refreshNonce}`] : [];
  const { language_hint } = getAiLocalePayload();
  const raw = await apiFetch("/ai/opener", {
    method: "POST",
    body: JSON.stringify({
      match_name: name.slice(0, 80),
      bio: String(input.bio || "").slice(0, 1000),
      interests: (input.interests || []).map((x) => String(x).trim()).filter(Boolean).slice(0, 24),
      city: String(input.city || "").slice(0, 120),
      tags: (input.tags || []).map((x) => String(x).trim()).filter(Boolean).slice(0, 12),
      locale: input.locale.slice(0, 12),
      language_hint,
      style: "playful",
      conversation_context,
    }),
    metaReason: "discover-inline-openers",
    skipThrottle: false,
    skipCache: true,
  });
  const obj = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const itemsRaw = Array.isArray(obj.items) ? obj.items : [];
  const items: DiscoverOpenerItem[] = itemsRaw
    .map((row: unknown) => {
      const r = row && typeof row === "object" ? (row as Record<string, unknown>) : {};
      return {
        type: String(r.type || "safe"),
        text: String(r.text || "").trim(),
      };
    })
    .filter((x) => Boolean(x.text));
  const sugRaw = Array.isArray(obj.suggestions) ? obj.suggestions : [];
  const suggestions = sugRaw
    .map((x: unknown) => String(x || "").trim())
    .filter(Boolean)
    .slice(0, 3);
  const outTexts = suggestions.length >= 3 ? suggestions : items.map((i) => i.text).filter(Boolean).slice(0, 3);
  return { items: items.slice(0, 3), suggestions: outTexts };
}
