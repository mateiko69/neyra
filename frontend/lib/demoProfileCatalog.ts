/**
 * Bundled catalog mirrors backend/scripts/generate_demo_profiles_json.py output:
 * `frontend/public/demo-profiles/demo_profiles.json`.
 * URLs are always `/demo-profiles/{men|women}/demo_NNN/main.jpg`.
 */

export type DemoPersonalityType = "playful" | "deep" | "calm" | "teasing";

export type DemoCatalogProfile = {
  id: string;
  gender?: string;
  display_name?: string;
  age?: number;
  city?: string;
  photo_main_path?: string;
  demo_personality?: {
    personality?: string;
    personality_type?: DemoPersonalityType | string;
  };
};

export type DemoProfilesCatalogFile = {
  version?: number;
  profiles: DemoCatalogProfile[];
};

export async function fetchDemoProfilesCatalog(signal?: AbortSignal): Promise<DemoProfilesCatalogFile | null> {
  try {
    const res = await fetch("/demo-profiles/demo_profiles.json", { signal, cache: "no-store" });
    if (!res.ok) return null;
    const data = (await res.json()) as DemoProfilesCatalogFile;
    if (!data || !Array.isArray(data.profiles)) return null;
    return data;
  } catch {
    return null;
  }
}

export function catalogProfilesWithBundledPhotos(rows: DemoCatalogProfile[]): DemoCatalogProfile[] {
  return rows.filter((p) => {
    const u = String(p.photo_main_path || "").trim();
    return /^\/demo-profiles\/(men|women)\/[^/]+\/main\.jpg$/i.test(u.split("?")[0] || "");
  });
}
