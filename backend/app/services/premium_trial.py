from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.user import User
from app.services.ab_engine import trial_days_for_user
from app.services.analytics import track_event

log = logging.getLogger("neyra.premium.trial")


def maybe_start_premium_trial(db: Session, *, user_id: int, reason: str) -> bool:
    """Start a premium trial once per user (length from A/B `growth.trial.duration`).

    Safety: never start a second trial (is_trial_used is sticky once set True).
    """
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        return False
    if bool(getattr(user, "is_trial_used", False)):
        return False
    now = datetime.now(UTC)
    until = getattr(user, "premium_until", None)
    if until is not None:
        # If already has a premium window for any reason, do not override.
        try:
            if getattr(until, "tzinfo", None) is None:
                until = until.replace(tzinfo=UTC)
            if now < until:
                return False
        except Exception:
            return False

    days = trial_days_for_user(db, int(user_id))
    user.premium_until = now + timedelta(days=days)
    user.is_trial_used = True  # sticky: indicates trial has been used
    user.trial_started_at = now
    db.add(user)
    db.commit()

    log.info("premium_trial_started user_id=%s reason=%s premium_until=%s", int(user_id), reason, user.premium_until.isoformat() if user.premium_until else None)
    track_event(db, "premium_trial_started", user_id=int(user_id), payload={"reason": reason, "days": days})
    return True

