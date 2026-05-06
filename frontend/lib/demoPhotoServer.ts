import "server-only";

import fs from "node:fs";
import path from "node:path";

/** Dev-only: warn if common demo assets are missing (server-only). */
export function devLogMissingDemoAssets(): void {
  if (process.env.NODE_ENV !== "development") return;
  try {
    const root = process.cwd();
    const base = path.join(root, "public", "demo-profiles");
    const checks = [
      path.join(base, "women", "demo_001", "main.jpg"),
      path.join(base, "men", "demo_001", "main.jpg"),
    ];
    for (const p of checks) {
      if (!fs.existsSync(p)) {
        // eslint-disable-next-line no-console
        console.warn("[demo-profiles] missing asset", p);
      }
    }
  } catch {
    /* ignore */
  }
}

