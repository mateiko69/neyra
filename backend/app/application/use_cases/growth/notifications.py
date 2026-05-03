from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.retention.notification_engine import NotificationEngine


def decide_notification(db: Session, user_id: int, event: dict) -> dict:
    return NotificationEngine().decide_notification(db, user_id, event).to_dict()

