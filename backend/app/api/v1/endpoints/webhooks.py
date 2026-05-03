from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Request
from app.api.deps import get_db
from app.services.analytics import track_event

router = APIRouter()

@router.post("/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    track_event(db, "stripe_webhook_received", payload={"bytes": len(payload)})
    return {"status": "received"}

@router.post("/app-store")
async def app_store_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    track_event(db, "app_store_webhook_received", payload=payload)
    return {"status": "received"}

@router.post("/play-store")
async def play_store_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    track_event(db, "play_store_webhook_received", payload=payload)
    return {"status": "received"}
