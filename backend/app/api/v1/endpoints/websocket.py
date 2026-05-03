from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from jose import jwt, JWTError
from app.core.config import settings
from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.models.profile import Profile
from app.models.match import Match
from app.models.message import Message
from app.services.demo_mode import is_demo_profile
from app.services.chat_manager import manager
from app.services.moderation import moderate_text
from app.services.events import publish_event
from app.services.moderation.message_risk_evaluator import MessageRiskEvaluator
from app.services.moderation.conversation_quality_evaluator import ConversationQualityEvaluator
from app.services.fraud.scam_signal_detector import ScamSignalDetector
from app.services.trust.action_policy import ActionPolicy, PolicyInput
from app.services.safety import is_blocked, ignored_user_ids

router = APIRouter()

def _is_prod() -> bool:
    return (settings.ENV or "").strip().lower() in ("production", "prod")


def _mint_ws_token(user_id: int, *, ttl_seconds: int = 90) -> str:
    ttl = max(60, min(int(ttl_seconds or 90), 120))
    exp = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    payload = {"sub": str(int(user_id)), "scope": "ws_chat", "exp": exp}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _decode_ws_token(websocket: WebSocket) -> int:
    """
    Prefer short-lived ws_token (scoped).
    Legacy ?token= is disabled (strict).
    """
    ws_token = (websocket.query_params.get("ws_token") or "").strip()
    if not _is_prod():
        # Dev-only diagnostics; never print full tokens.
        preview = (ws_token[:10] + "…") if ws_token else None
        print("WS DEBUG ws_token_preview:", preview)
    if not ws_token:
        raise WebSocketDisconnect(code=4401)
    try:
        payload = jwt.decode(ws_token, settings.SECRET_KEY, algorithms=["HS256"])
        sub = payload.get("sub")
        if not sub:
            raise WebSocketDisconnect(code=4401)
        uid = int(sub)
        if uid < 1:
            raise WebSocketDisconnect(code=4401)
        if str(payload.get("scope") or "") != "ws_chat":
            raise WebSocketDisconnect(code=4401)
        return uid
    except (JWTError, ValueError):
        raise WebSocketDisconnect(code=4401)


def _try_decode_ws_token(websocket: WebSocket) -> int | None:
    """
    Like _decode_ws_token, but returns None instead of raising.
    Used to avoid noisy ASGI exception logs by cleanly closing after accept.
    """
    ws_token = (websocket.query_params.get("ws_token") or "").strip()
    if not _is_prod():
        preview = (ws_token[:10] + "…") if ws_token else None
        print("WS DEBUG ws_token_preview:", preview)
        legacy = (websocket.query_params.get("token") or "").strip()
        if legacy:
            # Dev-only; legacy ?token= must be rejected (never accepted).
            print("WS DEBUG legacy_token_preview:", legacy[:10] + "…")
    if not ws_token:
        return None
    try:
        payload = jwt.decode(ws_token, settings.SECRET_KEY, algorithms=["HS256"])
        sub = payload.get("sub")
        if not sub:
            return None
        uid = int(sub)
        if uid < 1:
            return None
        if str(payload.get("scope") or "") != "ws_chat":
            return None
        return uid
    except (JWTError, ValueError):
        return None


@router.post("/ws/token")
def ws_token(current_user: User = Depends(get_current_user)):
    # Short-lived token scoped only to websocket chat.
    ttl = 90
    return {"ws_token": _mint_ws_token(current_user.id, ttl_seconds=ttl), "expires_in": ttl}


async def _ws_error(websocket: WebSocket, code: str) -> None:
    # Safe errors only; never leak internals.
    try:
        await websocket.send_json({"type": "error", "code": code})
    except Exception:
        # Ignore send failures; caller may disconnect.
        pass


@router.websocket("/ws/chat/{user_id}")
async def websocket_chat(websocket: WebSocket, user_id: int, db: Session = Depends(get_db)):
    # Auth: derive current user only from validated token (ws_token preferred).
    # Cleanly close when missing/invalid token (avoid ASGI exception spam).
    current_user_id = _try_decode_ws_token(websocket)
    if current_user_id is None:
        await websocket.accept()
        await websocket.close(code=4401)
        return
    if not _is_prod():
        print("WS DEBUG path_user_id:", int(user_id))
        print("WS DEBUG token_sub:", int(current_user_id))
        if int(user_id) != int(current_user_id):
            print("WS DEBUG sub_mismatch:", {"path_user_id": int(user_id), "token_sub": int(current_user_id)})
    # Path may be stale after client hydration; token is authoritative — keep connection alive.

    # Ensure user still exists (account deletion should immediately prevent WS usage).
    exists = db.query(User.id).filter(User.id == int(current_user_id)).first()
    if exists is None:
        raise WebSocketDisconnect(code=4401)

    await manager.connect(current_user_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if not isinstance(data, dict):
                await _ws_error(websocket, "invalid_payload")
                continue

            if str(data.get("type") or "").strip().lower() == "ping":
                try:
                    await websocket.send_json({"type": "pong"})
                except Exception:
                    break
                continue

            # Optional: if client sends sender_id, it must match the authenticated user.
            if "sender_id" in data:
                try:
                    claimed = int(data.get("sender_id") or 0)
                except Exception:
                    await _ws_error(websocket, "invalid_payload")
                    continue
                if claimed != int(current_user_id):
                    await _ws_error(websocket, "unauthorized")
                    continue

            try:
                receiver_id = int(data.get("receiver_id") or 0)
            except Exception:
                await _ws_error(websocket, "invalid_payload")
                continue
            if receiver_id < 1 or receiver_id == int(current_user_id):
                await _ws_error(websocket, "invalid_payload")
                continue

            content = str(data.get("content") or "").strip()
            context = data.get("conversation_context", []) or []
            if not content:
                await _ws_error(websocket, "invalid_payload")
                continue

            # Receiver authorization: must exist, must be matched, must not be blocked/ignored.
            receiver_exists = db.query(User.id).filter(User.id == int(receiver_id)).first() is not None
            if not receiver_exists:
                await _ws_error(websocket, "invalid_payload")
                continue

            if is_blocked(db, int(current_user_id), int(receiver_id)):
                await _ws_error(websocket, "blocked")
                continue

            ignored = ignored_user_ids(db, int(current_user_id))
            if ignored and int(receiver_id) in ignored:
                await _ws_error(websocket, "blocked")
                continue

            a, b = sorted([int(current_user_id), int(receiver_id)])
            matched = db.query(Match.id).filter(Match.user_a_id == a, Match.user_b_id == b).first() is not None
            if not matched:
                await _ws_error(websocket, "not_matched")
                continue

            # Do not trust client ownership fields.
            sender_id = int(current_user_id)

            msg_risk = MessageRiskEvaluator.evaluate_message_risk(content, context, allow_edgy_mode=False)
            convo_quality = ConversationQualityEvaluator.evaluate_conversation_quality(context + [content])
            scam = ScamSignalDetector.detect_scam_signals(None, context + [content])
            action, _reasons = ActionPolicy().decide(
                PolicyInput(message_risk=msg_risk.risk_score, scam_risk=scam.scam_risk, conversation_quality=convo_quality["quality_score"])
            )
            if action in {"hard_block", "soft_block"} or not msg_risk.allowed:
                await websocket.send_json(
                    {
                        "type": "rewrite_suggested" if msg_risk.rewrite_suggestion else "error",
                        "code": "blocked" if msg_risk.rewrite_suggestion else "invalid_payload",
                        "rewrite_suggestion": msg_risk.rewrite_suggestion,
                        "flags": msg_risk.flags,
                        "quality_flags": msg_risk.quality_flags,
                    }
                )
                continue
            moderation = moderate_text(content)
            if not moderation["allowed"]:
                await _ws_error(websocket, "invalid_payload")
                continue

            msg = Message(sender_id=sender_id, receiver_id=int(receiver_id), content=content)
            db.add(msg)
            db.commit()
            db.refresh(msg)
            payload = {
                "type": "message",
                "id": msg.id,
                "sender_id": int(sender_id),
                "receiver_id": int(receiver_id),
                "content": content,
                "created_at": msg.created_at.isoformat()
            }
            receiver_user = db.query(User).filter(User.id == int(receiver_id)).first()
            receiver_profile = db.query(Profile).filter(Profile.user_id == int(receiver_id)).first()
            sender_user = db.query(User).filter(User.id == int(sender_id)).first()
            receiver_demo = is_demo_profile(receiver_profile, receiver_user)
            sender_demo = bool(getattr(sender_user, "is_demo", False)) if sender_user else False
            await manager.send_to_user(int(sender_id), payload)
            if not receiver_demo:
                await manager.send_to_user(int(receiver_id), payload)
            try:
                if not receiver_demo and not sender_demo:
                    publish_event("message_sent", {"sender_id": int(sender_id), "receiver_id": int(receiver_id), "message_id": msg.id})
            except Exception:
                # Non-blocking: queue/redis may be unavailable in dev/tests.
                pass
    except WebSocketDisconnect:
        manager.disconnect(int(current_user_id), websocket)
