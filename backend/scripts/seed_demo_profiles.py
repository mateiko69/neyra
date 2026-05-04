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

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.demo_mode import (  # noqa: E402
    demo_profiles_json_path,
    purge_all_demo_users,
    repair_demo_profile_photos,
    sync_demo_profiles_from_catalog,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo profiles from demo_profiles.json")
    parser.add_argument(
        "--upsert-only",
        action="store_true",
        help="Skip purge; upsert catalog rows only (idempotent redeploy, keeps existing demo user ids).",
    )
    args = parser.parse_args()

    path = demo_profiles_json_path()
    print(f"Catalog path: {path}")
    if not path.is_file():
        print("Missing demo_profiles.json — run: python backend/scripts/generate_demo_profiles_json.py")
        sys.exit(1)
    db = SessionLocal()
    try:
        if args.upsert_only:
            print("Upsert-only mode: skipping purge")
        else:
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
        repaired = repair_demo_profile_photos(db)
        print(
            "Repair demo photos:",
            f"updated={repaired.get('updated', 0)}",
            f"total_demo_profiles={repaired.get('total_demo_profiles', 0)}",
        )
        for g in stats.get("gender_assigned") or []:
            print(f"  gender: {g}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
