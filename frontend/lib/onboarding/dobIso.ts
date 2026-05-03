/** DOB helpers: UI may be DMY or MDY; API is always YYYY-MM-DD (UTC calendar date). */

export function calendarDateValid(y: number, m: number, d: number): boolean {
  if (!Number.isFinite(y) || !Number.isFinite(m) || !Number.isFinite(d)) return false;
  if (y < 1900 || y > 2100 || m < 1 || m > 12 || d < 1 || d > 31) return false;
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d;
}

export function toIsoDate(y: number, m: number, d: number): string | null {
  if (!calendarDateValid(y, m, d)) return null;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${y}-${pad(m)}-${pad(d)}`;
}

export function fromIsoDate(iso: string): { y: number; m: number; d: number } | null {
  const s = String(iso || "").trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return null;
  const [ys, ms, ds] = s.split("-");
  const y = Number(ys);
  const m = Number(ms);
  const d = Number(ds);
  if (!calendarDateValid(y, m, d)) return null;
  return { y, m, d };
}

export function ageFromIsoUtc(iso: string): number | null {
  const parts = fromIsoDate(iso);
  if (!parts) return null;
  const { y, m, d } = parts;
  const dob = new Date(Date.UTC(y, m - 1, d));
  const now = new Date();
  let age = now.getUTCFullYear() - dob.getUTCFullYear();
  const mo = now.getUTCMonth() - dob.getUTCMonth();
  if (mo < 0 || (mo === 0 && now.getUTCDate() < dob.getUTCDate())) age -= 1;
  return age;
}

/** US-style month-first field order; most other app locales use day-first. */
export function useMonthDayYearFieldOrder(locale: string): boolean {
  return String(locale || "").trim().toLowerCase() === "en";
}
