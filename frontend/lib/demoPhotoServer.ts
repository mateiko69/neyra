import "server-only";

import fs from "node:fs";
import path from "node:path";

/** Dev-only: warn if common demo assets are missing (server-only). */
export function devLogMissingDemoAssets(): void {
  try {
    const root = process.cwd();
    const base = path.join(root, "public", "demo-profiles");
    const checks: string[] = [
      path.join(base, "women", "demo_001", "main.jpg"),
      path.join(base, "men", "demo_001", "main.jpg"),
    ];
    const roots = [path.join(base, "women"), path.join(base, "men")];
    for (const bucket of roots) {
      if (!fs.existsSync(bucket)) continue;
      for (const dir of fs.readdirSync(bucket, { withFileTypes: true })) {
        if (!dir.isDirectory()) continue;
        checks.push(path.join(bucket, dir.name, "main.jpg"));
      }
    }
    for (const p of checks) {
      if (!fs.existsSync(p)) {
        console.warn("[demo-profiles] missing asset", p);
      }
    }
  } catch {
    /* ignore */
  }
}

