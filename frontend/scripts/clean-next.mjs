import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const dir = path.join(root, ".next");

try {
  fs.rmSync(dir, { recursive: true, force: true });
} catch {
  // ignore
}

