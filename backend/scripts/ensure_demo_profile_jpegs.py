"""Create men/*/main.jpg and women/*/main.jpg for catalog + spec slugs (idempotent)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.services.demo_mode import DEMO_PROFILE_SPECS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT.parent / "frontend" / "public" / "demo-profiles"
CATALOG = FRONT / "demo_profiles.json"
SOURCE_DIR = FRONT / "shared"


def main() -> int:
    if not FRONT.is_dir():
        print("missing", FRONT)
        return 1
    pool = sorted(SOURCE_DIR.glob("avatar-*.jpg"))
    if not pool:
        print("missing pool jpgs in", SOURCE_DIR)
        return 1
    targets: list[Path] = []
    if CATALOG.is_file():
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
        profs = data.get("profiles") if isinstance(data, dict) else data
        if isinstance(profs, list):
            for p in profs:
                if not isinstance(p, dict):
                    continue
                cid = str(p.get("id") or "").strip()
                if not cid:
                    continue
                cl = cid.lower()
                if cl.startswith("man_"):
                    slug = cid[len("man_") :]
                    targets.append(FRONT / "men" / slug / "main.jpg")
                elif cl.startswith("woman_"):
                    slug = cid[len("woman_") :]
                    targets.append(FRONT / "women" / slug / "main.jpg")
    for spec in DEMO_PROFILE_SPECS:
        slug = str(spec["slug"])
        folder = "men" if str(spec.get("gender")) == "man" else "women"
        targets.append(FRONT / folder / slug / "main.jpg")

    seen = set()
    for i, dest in enumerate(targets):
        if dest in seen:
            continue
        seen.add(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = pool[i % len(pool)]
        shutil.copyfile(src, dest)
        print("ok", dest.relative_to(FRONT))

    # Mirror into backend/static for Railway Docker context (backend-only COPY).
    emb_root = BACKEND / "static" / "demo-profiles"
    if emb_root.parent.is_dir():
        for dest in targets:
            rel = dest.relative_to(FRONT)
            emb = emb_root / rel
            emb.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(dest, emb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
