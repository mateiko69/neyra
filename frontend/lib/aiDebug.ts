const truthy = new Set(["1", "true", "yes", "on"]);

/** Opt-in only: never defaults to true in dev (avoids “debug UI” masquerading as product). */
export const FORCE_AI_VISIBLE =
  process.env.NODE_ENV !== "production" &&
  truthy.has(String(process.env.NEXT_PUBLIC_AI_FORCE_UI ?? "").trim().toLowerCase());

const envDebugEnabled = truthy.has(String(process.env.NEXT_PUBLIC_AI_DEBUG ?? "").trim().toLowerCase());

export const AI_DEBUG_ENABLED = process.env.NODE_ENV !== "production" && (FORCE_AI_VISIBLE || envDebugEnabled);

export const AI_DEV_OVERRIDE_ACTIVE =
  process.env.NODE_ENV !== "production" && FORCE_AI_VISIBLE;

export function logAiData(label: string, response: unknown): void {
  if (!AI_DEBUG_ENABLED) return;
  console.log("AI DATA", { label, response });
}

export function logAiGate(label: string, payload: Record<string, unknown>): void {
  if (!AI_DEBUG_ENABLED) return;
  console.log("AI GATE", { label, ...payload });
}
