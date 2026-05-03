from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.device_token import DeviceToken
from app.services.push.service import get_push_provider

router = APIRouter()

@router.post("/register")
def register_device(payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    token = payload["token"]
    platform = payload.get("platform", "unknown")
    existing = db.query(DeviceToken).filter(DeviceToken.user_id == current_user.id, DeviceToken.token == token).first()
    if not existing:
        db.add(DeviceToken(user_id=current_user.id, platform=platform, token=token))
        db.commit()
    return {"status": "registered"}

@router.post("/test-push")
def test_push(payload: dict, current_user: User = Depends(get_current_user)):
    provider = get_push_provider()
    return provider.send(payload["token"], payload.get("title", "New match"), payload.get("body", "You have a new notification"))
