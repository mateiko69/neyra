from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.retention.engagement_engine import EngagementEngine


def calculate_engagement_state(db: Session, user_id: int) -> dict:
    return EngagementEngine().calculate_engagement_state(db, user_id).to_dict()

