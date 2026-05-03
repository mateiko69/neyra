from __future__ import annotations

from datetime import UTC, datetime

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User


def main() -> int:
    env = str(getattr(settings, "ENV", "") or "").strip().lower()
    if env in ("production", "prod"):
        print("ABORT: Not allowed in production.")
        return 2

    now = datetime.now(UTC)
    db = SessionLocal()
    try:
        updated = db.query(User).update({User.premium_until: None}, synchronize_session=False)
        db.commit()
    finally:
        db.close()

    print(f"DEV: revoked premium from {int(updated or 0)} users at {now.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

