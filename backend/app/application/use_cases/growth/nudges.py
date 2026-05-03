from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.growth.types import EngagementState
from app.services.retention.nudge_system import NudgeSystem


def generate_nudges(db: Session, user_id: int, engagement_state: dict) -> list[dict]:
    engagement = EngagementState(
        activity_level=engagement_state["activity_level"],
        last_active_hours=float(engagement_state["last_active_hours"]),
        matches_recent=int(engagement_state["matches_recent"]),
        messages_sent=int(engagement_state["messages_sent"]),
        reply_rate=float(engagement_state["reply_rate"]),
        drop_risk=int(engagement_state["drop_risk"]),
    )
    return NudgeSystem().generate_nudges(db, user_id, engagement)

