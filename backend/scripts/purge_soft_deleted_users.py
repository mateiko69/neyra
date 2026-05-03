"""
Permanently purge accounts whose soft-delete window expired.

This is a best-effort helper script intended to be run from a cron/job runner.

Behavior:
- Select users where is_deleted = true and deletion_scheduled_for <= now.
- Hard-delete user and related rows (irreversible).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User


def purge_expired_soft_deletes(db: Session, *, limit: int = 200) -> int:
    now = datetime.now(UTC)
    rows = (
        db.query(User)
        .filter(User.is_deleted == True)  # noqa: E712
        .filter(User.deletion_scheduled_for.isnot(None))
        .filter(User.deletion_scheduled_for <= now)
        .limit(max(1, min(limit, 2000)))
        .all()
    )
    if not rows:
        return 0

    # Import here to avoid side effects when script is imported.
    from app.api.v1.endpoints.account import hard_delete_user_id  # noqa

    deleted = 0
    for user in rows:
        hard_delete_user_id(db, int(user.id))
        deleted += 1
    return deleted


def main() -> None:
    engine = create_engine(settings.DATABASE_URL, future=True)
    with Session(engine) as db:
        count = purge_expired_soft_deletes(db)
        print(f"purged={count}")


if __name__ == "__main__":
    main()

