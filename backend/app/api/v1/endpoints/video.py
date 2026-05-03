from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.api_errors import api_error
from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.models.user import User
from app.services.match_partner import users_are_matched
from app.services.safety import is_blocked

router = APIRouter()


class CreateRoomIn(BaseModel):
    partner_user_id: int = Field(..., ge=1)


class CreateRoomOut(BaseModel):
    url: str


@router.post("/create-room", response_model=CreateRoomOut)
def create_room(payload: CreateRoomIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Daily.co room creator (MVP).
    - private room
    - exp: 1 hour
    - max participants: 2
    Matched-only + auth required.
    """
    partner_user_id = int(payload.partner_user_id)
    if partner_user_id == int(current_user.id):
        raise HTTPException(status_code=400, detail=api_error("chat.invalid_recipient"))
    if is_blocked(db, current_user.id, partner_user_id):
        raise HTTPException(status_code=403, detail=api_error("chat.user_blocked"))
    if not users_are_matched(db, current_user.id, partner_user_id):
        raise HTTPException(status_code=403, detail=api_error("chat.match_required"))

    domain = (settings.DAILY_DOMAIN or "").strip().rstrip("/")
    api_key = (settings.DAILY_API_KEY or "").strip()
    if not domain or not api_key:
        raise HTTPException(status_code=503, detail=api_error("video.daily_not_configured"))

    room_name = f"neyra-{uuid.uuid4().hex}"
    exp = int((datetime.now(UTC) + timedelta(hours=1)).timestamp())

    try:
        res = requests.post(
            "https://api.daily.co/v1/rooms",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "name": room_name,
                "privacy": "private",
                "properties": {
                    "exp": exp,
                    "max_participants": 2,
                },
            },
            timeout=8,
        )
    except Exception:
        raise HTTPException(status_code=503, detail=api_error("video.daily_unavailable"))

    if res.status_code >= 400:
        raise HTTPException(status_code=503, detail=api_error("video.daily_unavailable"))

    out = res.json() if res.content else {}
    url = str(out.get("url") or "").strip()
    if not url:
        url = f"https://{domain}/{room_name}"
    return {"url": url}

