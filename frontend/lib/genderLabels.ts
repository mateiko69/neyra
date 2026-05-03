/**
 * Normalize API/profile gender strings for UI badges (Discover, peek, etc.).
 */

export type GenderBucket = "male" | "female" | "nonbinary";

const MALE = new Set(["m", "male", "man", "guy", "masculine", "masculino", "hombre"]);
const FEMALE = new Set(["f", "female", "woman", "girl", "feminine", "femenino", "mujer"]);
const NB = new Set(["nb", "nonbinary", "non-binary", "non binary", "enby", "genderqueer"]);

export function genderBucketFromRaw(raw: string | null | undefined): GenderBucket | null {
  const s = String(raw ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
  if (!s) return null;
  if (MALE.has(s)) return "male";
  if (FEMALE.has(s)) return "female";
  if (NB.has(s)) return "nonbinary";
  if (s.includes("non-binary") || s.includes("nonbinary")) return "nonbinary";
  return null;
}
