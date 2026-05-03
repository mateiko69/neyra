"""Default Premium trial for every new account (no env vars required)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.user import User
from app.services.analytics import track_event

log = logging.getLogger("neyra.monetization.signup_trial")

# Product policy: all new users receive this Premium trial window.
SIGNUP_PREMIUM_TRIAL_DAYS = 5


def apply_signup_premium_trial(db: Session, *, user: User, source: str = "signup") -> None:
    """
    Grant a one-time Premium trial window stored on the user row.

    Sets premium_until / trial_* consistently so SubscriptionService can treat the user as
    effective tier `premium` during the window without a paid Paddle subscription.
    """
    now = datetime.now(UTC)
    until = now + timedelta(days=int(SIGNUP_PREMIUM_TRIAL_DAYS))
    user.premium_until = until
    user.trial_started_at = now
    user.trial_active = True
    user.trial_expires_at = until
    # Prevents conversion trial starter (`maybe_start_premium_trial`) from stacking another grant.
    user.is_trial_used = True
    db.add(user)
    try:
        track_event(
            db,
            "signup_premium_trial_started",
            user_id=int(user.id),
            payload={"source": source, "days": SIGNUP_PREMIUM_TRIAL_DAYS, "expires_at": until.isoformat()},
        )
    except Exception:
        pass
    log.info(
        "signup_trial_applied user_id=%s source=%s until=%s",
        int(user.id),
        source,
        until.isoformat(),
    )
