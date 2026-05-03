export const PAGE_BOOT_FETCH_DELAY_MS = 180;
export const PAGE_SECONDARY_FETCH_DELAY_MS = 420;

export function schedulePageLoad(task: () => void, delayMs: number = PAGE_BOOT_FETCH_DELAY_MS): () => void {
  if (typeof window === "undefined") {
    task();
    return () => {};
  }

  const timeoutId = window.setTimeout(task, delayMs);
  return () => {
    window.clearTimeout(timeoutId);
  };
}
