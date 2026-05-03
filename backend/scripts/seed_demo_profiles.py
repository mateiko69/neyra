#!/usr/bin/env python3
"""Seed demo users from frontend/public/demo-profiles/demo_profiles.json.

1) Purges all existing demo users (`is_demo=True`) and related rows (messages, matches, AI memory, …).
2) Inserts fresh demo users from the JSON catalog only (gender is never randomized).

Does not send messages. Real users are never deleted.

Usage (from repo root):
  python backend/scripts/seed_demo_profiles.py

Or from backend/:
  python scripts/seed_demo_profiles.py

Docker (compose mounts ./frontend → /app/frontend so the catalog is visible):
  docker compose exec api python scripts/generate_demo_profiles_json.py
  docker compose exec api python scripts/seed_demo_profiles.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.demo_mode import (  # noqa: E402
    demo_profiles_json_path,
    purge_all_demo_users,
    sync_demo_profiles_from_catalog,
)


def main() -> None:
    path = demo_profiles_json_path()
    print(f"Catalog path: {path}")
    if not path.is_file():
        print("Missing demo_profiles.json — run: python backend/scripts/generate_demo_profiles_json.py")
        sys.exit(1)
    db = SessionLocal()
    try:
        purged = purge_all_demo_users(db)
        print(
            "Purge demo users:",
            f"removed_users={purged.get('removed_users', 0)}",
            f"messages_deleted={purged.get('messages_deleted', 0)}",
            f"matches_deleted={purged.get('matches_deleted', 0)}",
        )
        stats = sync_demo_profiles_from_catalog(db)
        if not stats.get("ok"):
            sys.exit(2)
        for g in stats.get("gender_assigned") or []:
            print(f"  gender: {g}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
