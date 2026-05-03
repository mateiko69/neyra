from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.domain.matching.utils import clamp_int
from app.domain.growth.config import DEFAULT_GROWTH_CONFIG, GrowthConfig
from app.domain.growth.types import EngagementState
from app.models.match import Match
from app.models.message import Message


class EngagementEngine:
    """Computes retention/engagement state from app activity.

    This intentionally avoids dark patterns: it measures momentum & drop risk
    without inventing urgency.
    """

    def __init__(self, config: GrowthConfig = DEFAULT_GROWTH_CONFIG):
        self._c = config

    def calculate_engagement_state(self, db: Session, user_id: int) -> EngagementState:
        now = datetime.now(UTC)

        last_msg = (
            db.query(Message)
            .filter((Message.sender_id == user_id) | (Message.receiver_id == user_id))
            .order_by(Message.created_at.desc())
            .first()
        )
        last_active_at = last_msg.created_at if last_msg else None
        last_active_hours = ((now - last_active_at).total_seconds() / 3600) if last_active_at else 999.0

        recent_window = now - timedelta(days=7)
        matches_recent = (
            db.query(Match)
            .filter(((Match.user_a_id == user_id) | (Match.user_b_id == user_id)) & (Match.created_at >= recent_window))
            .count()
        )

        sent_recent = (
            db.query(Message)
            .filter((Message.sender_id == user_id) & (Message.created_at >= recent_window))
            .count()
        )
        received_recent = (
            db.query(Message)
            .filter((Message.receiver_id == user_id) & (Message.created_at >= recent_window))
            .count()
        )

        messages_sent = sent_recent
        reply_rate = (received_recent / max(1, sent_recent)) * 100.0

        # Drop risk: inactivity + low replies + matches without messages.
        inactivity_penalty = min(last_active_hours / self._c.inactive_hours_low, 1.0) * 55
        reply_penalty = max(0.0, 60.0 - min(reply_rate, 100.0)) * 0.5
        momentum_bonus = min(messages_sent, 30) * 0.6 + min(matches_recent, 10) * 1.2
        drop_risk = clamp_int(inactivity_penalty + reply_penalty - momentum_bonus + 35)

        activity_level = "low"
        if last_active_hours <= self._c.inactive_hours_medium and messages_sent >= 6:
            activity_level = "high"
        elif last_active_hours <= self._c.inactive_hours_low:
            activity_level = "medium"

        return EngagementState(
            activity_level=activity_level,
            last_active_hours=round(last_active_hours, 2),
            matches_recent=matches_recent,
            messages_sent=messages_sent,
            reply_rate=round(min(reply_rate, 100.0), 1),
            drop_risk=drop_risk,
        )

