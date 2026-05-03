from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.services.monetization.smart_engine import SmartMonetizationEngine

router = APIRouter()

_engine = SmartMonetizationEngine()


@router.post("/event")
def track_monetization_event(payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    event_type = str(payload.get("eventType") or payload.get("event_type") or "").strip()
    if not event_type:
        raise HTTPException(status_code=400, detail="eventType required")
    metadata = payload.get("metadata")
    metadata_obj = metadata if isinstance(metadata, dict) else {}
    # Validate event type via engine Literal set (best effort; keep forward-compatible)
    allowed = {
        "like_received",
        "match_created",
        "message_sent",
        "message_ignored",
        "chat_idle",
        "boost_used",
        "swipe_limit_reached",
    }
    if event_type not in allowed:
        raise HTTPException(status_code=400, detail="unsupported eventType")
    return _engine.track_user_event(db, int(current_user.id), event_type, metadata=metadata_obj)

