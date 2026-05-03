from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User


def main() -> int:
    env = str(getattr(settings, "ENV", "") or "").strip().lower()
    if env in ("production", "prod"):
        print("ABORT: Not allowed in production.")
        return 2

    now = datetime.now(UTC)
    new_until = now + timedelta(days=90)

    db = SessionLocal()
    try:
        updated = (
            db.query(User)
            .filter((User.premium_until.is_(None)) | (User.premium_until < now))
            .update({User.premium_until: new_until}, synchronize_session=False)
        )
        db.commit()
    finally:
        db.close()

    print(f"DEV: granted premium to {int(updated or 0)} users at {now.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

