import { isRequestAborted } from "../api";

/** Never show these as user-visible thread/inbox errors. */
export function isBenignChatRequestFailure(error: unknown): boolean {
  if (isRequestAborted(error)) return true;
  if (error instanceof Error) {
    const m = error.message.toLowerCase();
    if (m.includes("abort") || m === "request aborted") return true;
  }
  return false;
}

export function formatChatUserError(
  error: unknown,
  fallback: string,
  localizeMessage?: (message: string) => string,
): string {
  if (isBenignChatRequestFailure(error)) return "";
  if (error instanceof Error && error.message.trim()) {
    const message = error.message.trim();
    return localizeMessage ? localizeMessage(message) : message;
  }
  return localizeMessage ? localizeMessage(fallback) : fallback;
}
