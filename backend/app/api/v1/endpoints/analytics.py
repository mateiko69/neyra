from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.services.analytics import track_event

router = APIRouter()

@router.post("/track")
def track(payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    event = track_event(db, payload["name"], user_id=current_user.id, payload=payload.get("payload", {}))
    return {"event_id": event.id, "name": event.name}


@router.post("/track/batch")
def track_batch(payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    raw = payload.get("events")
    if not isinstance(raw, list) or len(raw) == 0:
        raise HTTPException(status_code=400, detail="events[] required")
    out: list[dict] = []
    for item in raw[:40]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        pl = item.get("payload")
        payload_obj = pl if isinstance(pl, dict) else {}
        ev = track_event(db, name, user_id=current_user.id, payload=payload_obj)
        out.append({"event_id": ev.id, "name": ev.name})
    return {"events": out}
