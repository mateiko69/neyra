/**
 * Opt-in chat flow tracing. Set NEXT_PUBLIC_DEBUG_CHAT=1 or run a development build.
 */
export const DEBUG_CHAT_FLOW =
  typeof process !== "undefined" &&
  (process.env.NEXT_PUBLIC_DEBUG_CHAT === "1" || process.env.NODE_ENV === "development");

export function debugChat(...args: unknown[]): void {
  if (DEBUG_CHAT_FLOW) console.log("[neyra chat]", ...args);
}
