import { wireFromFastApiDetailArray } from "./i18n/fastApiValidation";

/** Parse FastAPI-style error bodies into a short user-visible string. */
export function formatApiError(text: string, status: number): string {
  const fallback = text?.trim() || `Request failed (${status})`;
  try {
    const j = JSON.parse(text) as { detail?: unknown };
    const d = j?.detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object" && !Array.isArray(d)) {
      const obj = d as { code?: unknown; error?: unknown; message?: unknown; detail?: unknown };
      if (typeof obj.code === "string" && obj.code.trim()) {
        const code = obj.code.trim();
        const part = (obj as { part?: unknown }).part;
        const max = (obj as { max?: unknown }).max;
        if (code === "upload.item_failed" && typeof part === "number" && Number.isFinite(part)) {
          return `${code}\t${String(Math.trunc(part))}`;
        }
        if (code === "upload.too_many_files" && typeof max === "number" && Number.isFinite(max)) {
          return `${code}\t${String(Math.trunc(max))}`;
        }
        return code;
      }
      const msg =
        typeof obj.message === "string"
          ? obj.message
          : typeof obj.detail === "string"
            ? obj.detail
            : typeof obj.error === "string"
              ? obj.error
              : "";
      if (msg.trim()) return msg.trim();
    }
    if (Array.isArray(d)) {
      const wire = wireFromFastApiDetailArray(d);
      if (wire) return wire;
      const parts = d.map((x: { msg?: string; type?: string }) => x?.msg || JSON.stringify(x));
      return parts.filter(Boolean).join("; ") || fallback;
    }
  } catch {
    /* not JSON */
  }
  return fallback;
}
