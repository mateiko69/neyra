import json
from sqlalchemy.orm import Session
from app.models.analytics_event import AnalyticsEvent

def track_event(db: Session, name: str, user_id: int | None = None, payload: dict | None = None):
    event = AnalyticsEvent(user_id=user_id, name=name, payload_json=json.dumps(payload or {}))
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
