/** Client-side hint when /messages/quality was skipped (e.g. already warned) but the draft looks engaged. */
export function messageFeelsEngagingHeuristic(text: string): boolean {
  const t = String(text || "").trim();
  if (t.length < 22) return false;
  const words = t.split(/\s+/).filter(Boolean);
  if (words.length < 5) return false;
  if (/[?]/.test(t)) return true;
  if (words.length >= 10) return true;
  const lower = t.toLowerCase();
  if (/(^|\s)(i|i'm|i’ve|we|you|your)\s/.test(lower) && words.length >= 6) return true;
  return false;
}
