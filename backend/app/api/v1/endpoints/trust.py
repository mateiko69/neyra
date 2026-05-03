from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Body, HTTPException

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.profile import Profile
from app.services.analytics import track_event

from app.application.use_cases.trust_and_safety.evaluate_profile import evaluate_profile_risk
from app.application.use_cases.trust_and_safety.evaluate_message import evaluate_message_risk
from app.application.use_cases.trust_and_safety.evaluate_conversation import evaluate_conversation_quality
from app.application.use_cases.trust_and_safety.evaluate_scam import detect_scam_signals
from app.application.use_cases.trust_and_safety.evaluate_bot import detect_bot_signals


router = APIRouter()


@router.post("/profile/evaluate")
def trust_profile_evaluate(
    payload: dict = Body(default={}),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Default: evaluate current user's profile unless user_id is provided (admin tooling later).
    user_id = int(payload.get("user_id", current_user.id))
    profile = db.query(Profile).filter(Profile.user_id == user_id).first()
    result = evaluate_profile_risk(profile)
    if result["risk_score"] >= 60:
        track_event(db, "suspicious_profile_detected", user_id=user_id, payload=result)
    return result


@router.post("/message/evaluate")
def trust_message_evaluate(
    payload: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    message = str(payload.get("message", "")).strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    context = payload.get("conversation_context", []) or []
    allow_edgy_mode = bool(payload.get("allow_edgy_mode", False))
    result = evaluate_message_risk(message, context, allow_edgy_mode=allow_edgy_mode)
    if result["risk_score"] >= 55 or not result["allowed"]:
        track_event(db, "suspicious_message_detected", user_id=current_user.id, payload=result)
    return result


@router.post("/conversation/evaluate")
def trust_conversation_evaluate(
    payload: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    messages = payload.get("messages", []) or []
    result = evaluate_conversation_quality(messages)
    if result["quality_score"] <= 45:
        track_event(db, "conversation_quality_low", user_id=current_user.id, payload=result)
    if "cringe_lines" in result.get("flags", []):
        track_event(db, "cringe_warning_triggered", user_id=current_user.id, payload=result)
    return result


@router.post("/scam/evaluate")
def trust_scam_evaluate(
    payload: dict = Body(default={}),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = int(payload.get("user_id", current_user.id))
    profile = db.query(Profile).filter(Profile.user_id == user_id).first()
    messages = payload.get("messages", []) or []
    result = detect_scam_signals(profile, messages)
    if result["scam_risk"] >= 70:
        track_event(db, "possible_scam_detected", user_id=user_id, payload=result)
    return result


@router.post("/bot/evaluate")
def trust_bot_evaluate(
    payload: dict = Body(default={}),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = int(payload.get("user_id", current_user.id))
    profile = db.query(Profile).filter(Profile.user_id == user_id).first()
    behavior_data = payload.get("behavior_data", {}) or {}
    result = detect_bot_signals(profile, behavior_data)
    if result["bot_probability"] >= 70:
        track_event(db, "possible_bot_detected", user_id=user_id, payload=result)
    return result

