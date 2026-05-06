import json
import logging
from sqlalchemy.orm import Session
from app.models.analytics_event import AnalyticsEvent

_log = logging.getLogger(__name__)


def track_event(db: Session, name: str, user_id: int | None = None, payload: dict | None = None):
    """Best-effort analytics row — must never break matching / swipes if the events table hiccups."""
    try:
        event = AnalyticsEvent(user_id=user_id, name=name, payload_json=json.dumps(payload or {}))
        db.add(event)
        db.commit()
        db.refresh(event)
        return event
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        _log.warning("track_event_failed name=%s user_id=%s error=%s", name, user_id, exc)
        return None
