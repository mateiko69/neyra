/** Caps viral share prompts per browser tab session (non-spam). */

const SESSION_COUNT_KEY = "neyra:viral_share_prompt_count";
const MAX_PROMPTS_PER_SESSION = 2;

export function getViralSharePromptSessionCount(): number {
  if (typeof window === "undefined") return 0;
  try {
    const raw = sessionStorage.getItem(SESSION_COUNT_KEY);
    const n = Number.parseInt(String(raw || "0"), 10);
    return Number.isFinite(n) && n >= 0 ? n : 0;
  } catch {
    return 0;
  }
}

export function incrementViralSharePromptSessionCount(): number {
  const next = getViralSharePromptSessionCount() + 1;
  try {
    sessionStorage.setItem(SESSION_COUNT_KEY, String(next));
  } catch {
    /* private mode */
  }
  return next;
}

export function canOfferViralSharePrompt(): boolean {
  return getViralSharePromptSessionCount() < MAX_PROMPTS_PER_SESSION;
}
