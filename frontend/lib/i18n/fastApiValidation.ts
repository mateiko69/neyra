/**
 * Maps FastAPI / Pydantic v2 `detail` arrays (422) to a stable wire message for i18n.
 * Wire shapes:
 * - Single: validation\t<kind>\t<fieldKey>
 * - Multiple (2–3): validation\tmulti\t<kind1>\t<field1>\t<kind2>\t<field2>…
 * — no raw Pydantic `msg` text is included.
 */

export type ValidationWireKind =
  | "required"
  | "email"
  | "too_short"
  | "too_long"
  | "invalid_type"
  | "invalid_choice"
  | "generic";

type ValidationItem = {
  type?: unknown;
  loc?: unknown;
  msg?: unknown;
};

export type ValidationEntry = {
  kind: ValidationWireKind;
  field: string;
  order: number;
};

/** Lower = surfaced first (most important). */
const PRIORITY: Record<ValidationWireKind, number> = {
  required: 0,
  email: 1,
  too_short: 2,
  too_long: 3,
  invalid_choice: 4,
  invalid_type: 5,
  generic: 6,
};

const LOC_PREFIX = new Set(["body", "query", "header", "path", "cookie"]);

const MAX_VALIDATION_ERRORS = 3;

function isPydanticValidationItem(x: unknown): x is ValidationItem {
  if (!x || typeof x !== "object" || Array.isArray(x)) return false;
  const o = x as ValidationItem;
  return typeof o.type === "string" && Array.isArray(o.loc);
}

/** Last field-like segment in `loc` (e.g. ["body","email"] → "email"). */
export function fieldKeyFromLoc(loc: unknown): string {
  if (!Array.isArray(loc)) return "";
  let last = "";
  for (const seg of loc) {
    if (typeof seg !== "string") continue;
    if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(seg)) continue;
    if (seg === "__root__" || seg.startsWith("__")) continue;
    last = seg;
  }
  if (last && LOC_PREFIX.has(last)) return "";
  return last;
}

function msgLower(item: ValidationItem): string {
  return String(item.msg ?? "").toLowerCase();
}

export function mapItemToKind(item: ValidationItem): ValidationWireKind | null {
  const t = String(item.type || "");
  const msg = msgLower(item);

  if (t === "missing") return "required";
  if (t === "string_too_short") return "too_short";
  if (t === "string_too_long") return "too_long";
  if (t === "enum" || t === "literal_error" || t === "union_tag_invalid") return "invalid_choice";

  if (t === "value_error") {
    if (msg.includes("email") || msg.includes("@-sign") || msg.includes("@ sign")) return "email";
    if (msg.includes("required")) return "required";
    return "generic";
  }

  if (t === "date_from_datetime_parsing" || t === "time_from_datetime_parsing" || t === "datetime_from_date_parsing") {
    return "invalid_type";
  }

  if (t.endsWith("_type")) return "invalid_type";
  if (t.endsWith("_parsing")) return "invalid_type";

  return null;
}

function kindForItem(item: ValidationItem): ValidationWireKind {
  return mapItemToKind(item) ?? "generic";
}

/**
 * Collects up to {@link MAX_VALIDATION_ERRORS} errors: dedupes by field (keeps most important kind),
 * then sorts by priority and original order.
 */
export function prioritizeValidationEntries(entries: ValidationEntry[]): ValidationEntry[] {
  const byField = new Map<string, ValidationEntry>();
  for (const entry of entries) {
    const dedupeKey = entry.field || `\0${entry.order}`;
    const prev = byField.get(dedupeKey);
    if (!prev || PRIORITY[entry.kind] < PRIORITY[prev.kind]) {
      byField.set(dedupeKey, entry);
    }
  }
  const merged = [...byField.values()];
  merged.sort((a, b) => PRIORITY[a.kind] - PRIORITY[b.kind] || a.order - b.order);
  return merged.slice(0, MAX_VALIDATION_ERRORS);
}

export function entriesFromFastApiDetailArray(detail: unknown): ValidationEntry[] | null {
  if (!Array.isArray(detail) || detail.length === 0) return null;
  if (!detail.every(isPydanticValidationItem)) return null;

  return detail.map((item, order) => ({
    kind: kindForItem(item),
    field: fieldKeyFromLoc(item.loc),
    order,
  }));
}

/**
 * If `detail` looks like a Pydantic validation list, returns a wire string; otherwise `null`.
 */
export function wireFromFastApiDetailArray(detail: unknown): string | null {
  const rawEntries = entriesFromFastApiDetailArray(detail);
  if (!rawEntries) return null;

  const picked = prioritizeValidationEntries(rawEntries);
  if (picked.length === 0) return null;

  if (picked.length === 1) {
    const e = picked[0];
    return `validation\t${e.kind}\t${e.field}`;
  }

  const tail = picked.flatMap((e) => [e.kind, e.field]).join("\t");
  return `validation\tmulti\t${tail}`;
}
