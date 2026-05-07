import logging
from datetime import UTC, datetime
import hashlib
import re

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Request
from app.api.api_errors import api_error
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.message import Message
from app.models.message_reaction import MessageReaction
from app.models.match import Match
from app.models.profile import Profile
from app.models.thread_read_state import ThreadReadState
from app.utils.media_urls import normalize_media_url, normalize_photo_url
from app.schemas.message import MessageCreate
from app.services.moderation import moderate_text
from app.services.moderation.message_risk_evaluator import MessageRiskEvaluator
from app.services.moderation.conversation_quality_evaluator import ConversationQualityEvaluator
from app.services.analytics import track_event
from app.services.ai_product_analytics import pop_ai_suggestion_wave
from app.services.events import publish_event
from app.services.chat_manager import manager
from app.services.fraud.scam_signal_detector import ScamSignalDetector
from app.services.trust.profile_risk_evaluator import ProfileRiskEvaluator
from app.services.trust.action_policy import ActionPolicy, PolicyInput
from app.services.match_partner import users_are_matched
from app.services.safety import blocked_user_ids, is_blocked
from app.services.ai.cache import get_redis
from app.services.trust.profile_quality import compute_profile_quality
from app.services.trust.verification_state import is_verified_profile
from app.services.premium_trial import maybe_start_premium_trial
from app.services.demo_behavior import note_real_user_message_to_demo
from app.services.demo_behavior import run_demo_behavior_tick
from app.core.config import settings
from app.services.ai.locale_pipeline import resolve_http_ai_locale
from app.services.ai.localized_demo_text import (
    coerce_demo_partner_message_body,
    localized_demo_chat_banner,
    localized_demo_profile_badge,
    localized_voice_message_stub,
    three_demo_openers,
)
from app.services.demo_mode import (
    build_demo_reply,
    is_demo_live_enabled,
    is_demo_mode_enabled,
    is_demo_profile,
)

router = APIRouter()
logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")

_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF]")
_LAUGH_RE = re.compile(r"\b(lol|lmao|haha|hehe)\b", re.IGNORECASE)


def _message_features(text: str) -> dict:
    """Privacy-safe, aggregate-only features for learning (no raw text stored)."""
    s = str(text or "").strip()
    if not s:
        return {}
    length = len(s)
    has_question = ("?" in s) or ("？" in s)
    has_emoji = bool(_EMOJI_RE.search(s))
    exclam = s.count("!")
    laugh = bool(_LAUGH_RE.search(s)) or ("😂" in s) or ("🤣" in s)
    playful = bool(has_emoji or exclam >= 2 or laugh)
    tone = "playful" if playful else "serious"
    bucket = "short" if length < 70 else "medium" if length < 140 else "long"
    return {
        "length": int(length),
        "length_bucket": bucket,
        "has_question": bool(has_question),
        "has_emoji": bool(has_emoji),
        "tone": tone,
    }


def _norm_message_for_hash(text: str) -> str:
    t = (text or "").strip().lower()
    t = _WS_RE.sub(" ", t)
    return t


def _hash_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


@router.post("/quality")
def message_quality(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Lightweight, non-blocking quality analysis (no message is created).
    Used for conversion nudges (rewrite/upsell) before sending.
    """
    receiver_id = payload.get("receiver_id")
    content = str(payload.get("content") or "").strip()
    ctx = payload.get("conversation_context") or []
    if not receiver_id or not str(receiver_id).strip():
        raise HTTPException(status_code=400, detail=api_error("chat.invalid_recipient"))
    try:
        receiver_id = int(receiver_id)
    except Exception:
        raise HTTPException(status_code=400, detail=api_error("chat.invalid_recipient"))
    if receiver_id == int(current_user.id):
        raise HTTPException(status_code=400, detail=api_error("chat.invalid_recipient"))
    if not users_are_matched(db, current_user.id, receiver_id):
        raise HTTPException(status_code=403, detail=_not_matched_detail())
    if is_blocked(db, current_user.id, receiver_id):
        raise HTTPException(status_code=403, detail=api_error("chat.user_blocked"))
    if not content:
        return {"ok": True, "may_not_get_reply": False, "risk_score": 0, "quality_flags": [], "rewrite_suggestion": None}

    ctx_lines = []
    if isinstance(ctx, list):
        for line in ctx[-15:]:
            s = str(line or "").strip()
            if s:
                ctx_lines.append(s[:8000])

    msg_risk = MessageRiskEvaluator.evaluate_message_risk(content, ctx_lines, allow_edgy_mode=False)
    convo_quality = ConversationQualityEvaluator.evaluate_conversation_quality(ctx_lines + [content])
    cq_score = int(convo_quality.get("quality_score") or 0)
    risk = int(msg_risk.risk_score or 0)
    may_not_get_reply = bool(msg_risk.rewrite_suggestion) or risk >= 55 or cq_score <= 45
    feels_engaging = bool(
        not may_not_get_reply
        and cq_score >= 58
        and risk < 42
        and len(content) >= 20
    )

    try:
        track_event(
            db,
            "message_quality_analyzed",
            user_id=current_user.id,
            payload={
                "receiver_id": int(receiver_id),
                "may_not_get_reply": bool(may_not_get_reply),
                "risk_score": int(msg_risk.risk_score or 0),
                "quality_flags": msg_risk.quality_flags or [],
            },
        )
    except Exception:
        pass

    return {
        "ok": True,
        "may_not_get_reply": bool(may_not_get_reply),
        "risk_score": risk,
        "quality_flags": msg_risk.quality_flags or [],
        "rewrite_suggestion": msg_risk.rewrite_suggestion,
        "conversation_quality_score": cq_score,
        "feels_engaging": bool(feels_engaging),
    }


def _touch_thread_read(db: Session, user_id: int, partner_user_id: int) -> None:
    now = datetime.now(UTC)
    row = (
        db.query(ThreadReadState)
        .filter(ThreadReadState.user_id == user_id, ThreadReadState.partner_user_id == partner_user_id)
        .first()
    )
    if row:
        row.last_read_at = now
    else:
        db.add(ThreadReadState(user_id=user_id, partner_user_id=partner_user_id, last_read_at=now))
    db.commit()


def _not_matched_detail() -> dict:
    return api_error("chat.match_required")


def _log_unmatched_attempt(current_user_id: int, other_user_id: int, action: str) -> None:
    try:
        logger.warning(
            "unmatched_access_attempt action=%s user_id=%s other_user_id=%s",
            action,
            int(current_user_id),
            int(other_user_id),
        )
    except Exception:
        # Logging must never break request handling.
        pass


@router.get("/conversations")
def list_conversations(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 80,
    prioritize_verified: bool = False,
):
    limit = max(1, min(limit, 120))
    blocked = blocked_user_ids(db, current_user.id)
    match_rows = (
        db.query(Match)
        .filter((Match.user_a_id == current_user.id) | (Match.user_b_id == current_user.id))
        .order_by(Match.created_at.desc())
        .limit(limit)
        .all()
    )
    partner_ids = []
    for row in match_rows:
        pid = row.user_b_id if row.user_a_id == current_user.id else row.user_a_id
        if blocked and pid in blocked:
            continue
        partner_ids.append(pid)

    profiles = (
        {p.user_id: p for p in db.query(Profile).filter(Profile.user_id.in_(partner_ids)).all()}
        if partner_ids
        else {}
    )
    users_map = {u.id: u for u in db.query(User).filter(User.id.in_(partner_ids)).all()} if partner_ids else {}
    read_map = {}
    if partner_ids:
        for r in (
            db.query(ThreadReadState)
            .filter(
                ThreadReadState.user_id == current_user.id,
                ThreadReadState.partner_user_id.in_(partner_ids),
            )
            .all()
        ):
            read_map[r.partner_user_id] = r.last_read_at

    ui_loc = resolve_http_ai_locale(request, db=db, user_id=int(current_user.id))

    out = []
    for row in match_rows:
        partner_id = row.user_b_id if row.user_a_id == current_user.id else row.user_a_id
        if blocked and partner_id in blocked:
            continue
        profile = profiles.get(partner_id)
        first_photo = None
        if profile and profile.photo_urls:
            parts = [x.strip() for x in profile.photo_urls.split(",") if x.strip()]
            if parts:
                first_photo = normalize_photo_url(parts[0], demo_profile_gender=getattr(profile, "gender", None)) or None
        last = (
            db.query(Message)
            .filter(
                or_(
                    and_(Message.sender_id == current_user.id, Message.receiver_id == partner_id),
                    and_(Message.sender_id == partner_id, Message.receiver_id == current_user.id),
                )
            )
            .order_by(Message.created_at.desc())
            .first()
        )
        cutoff = read_map.get(partner_id)
        unread_q = db.query(Message).filter(Message.sender_id == partner_id, Message.receiver_id == current_user.id)
        if cutoff is not None:
            unread_q = unread_q.filter(Message.created_at > cutoff)
        unread_count = unread_q.count()
        partner_user_row = users_map.get(partner_id)
        preview = ""
        if last:
            preview = (last.content or "").strip()
            if not preview and getattr(last, "voice_url", None):
                preview = localized_voice_message_stub(ui_loc)
            partner_is_demo_pf = is_demo_profile(profile, partner_user_row)
            if partner_is_demo_pf and last.sender_id == partner_id:
                preview = coerce_demo_partner_message_body(
                    raw_db=preview,
                    locale=ui_loc,
                    message_id=int(last.id),
                    sender_is_demo_bot=True,
                    route="GET /messages/conversations",
                )
            if len(preview) > 140:
                preview = preview[:137] + "…"
        partner_is_verified = bool(is_verified_profile(profile)) if profile else False
        partner_quality = compute_profile_quality(profile) if profile else None
        partner_low_quality = bool(partner_quality and partner_quality.quality_flag == "low_quality")
        partner_is_demo = is_demo_profile(profile, partner_user_row)
        out.append(
            {
                "match_id": row.id,
                "partner_user_id": partner_id,
                "partner_display_name": profile.display_name if profile else "Unknown",
                "partner_photo": first_photo,
                "partner_verified": partner_is_verified,
                "partner_low_quality": partner_low_quality,
                "partner_is_demo_profile": partner_is_demo,
                "demo_label": localized_demo_profile_badge(ui_loc) if partner_is_demo else None,
                "demo_disclaimer": (
                    ((getattr(profile, "demo_disclaimer", "") or "").strip() or localized_demo_profile_badge(ui_loc))
                    if partner_is_demo
                    else None
                ),
                "demo_chat_label": localized_demo_chat_banner(ui_loc) if partner_is_demo else None,
                "last_message_preview": preview,
                "last_message_at": last.created_at.isoformat() if last and last.created_at else None,
                "unread_count": unread_count,
            }
        )

    def sort_key(item: dict):
        t = item.get("last_message_at") or ""
        verified_score = 1 if (prioritize_verified and bool(item.get("partner_verified"))) else 0
        non_low_quality_score = 0 if bool(item.get("partner_low_quality")) else 1
        return (verified_score, non_low_quality_score, t)

    out.sort(key=sort_key, reverse=True)
    return out


@router.get("/{partner_user_id}")
def get_thread(
    request: Request,
    partner_user_id: int,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if is_blocked(db, current_user.id, partner_user_id):
        raise HTTPException(status_code=403, detail=api_error("chat.user_blocked"))
    if not users_are_matched(db, current_user.id, partner_user_id):
        _log_unmatched_attempt(current_user.id, partner_user_id, action="thread_get")
        raise HTTPException(status_code=403, detail=_not_matched_detail())
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    rows = (
        db.query(Message)
        .filter(
            ((Message.sender_id == current_user.id) & (Message.receiver_id == partner_user_id))
            | ((Message.sender_id == partner_user_id) & (Message.receiver_id == current_user.id))
        )
        .order_by(Message.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    rows.reverse()
    ui_loc = resolve_http_ai_locale(request, db=db, user_id=int(current_user.id))
    partner_profile_t = db.query(Profile).filter(Profile.user_id == int(partner_user_id)).first()
    partner_user_t = db.query(User).filter(User.id == int(partner_user_id)).first()
    demo_thread = is_demo_profile(partner_profile_t, partner_user_t)
    base_msgs = [_message_to_json(m) for m in rows]
    for p in base_msgs:
        if demo_thread and int(p.get("sender_id") or 0) == int(partner_user_id):
            p["content"] = coerce_demo_partner_message_body(
                raw_db=str(p.get("content") or ""),
                locale=ui_loc,
                message_id=int(p.get("id") or 0),
                sender_is_demo_bot=True,
                route="GET /messages/partner_thread",
            )
    payload = _attach_reactions(db, current_user.id, base_msgs)
    _touch_thread_read(db, current_user.id, partner_user_id)
    a, b = sorted([int(current_user.id), int(partner_user_id)])
    match_row = db.query(Match).filter(Match.user_a_id == a, Match.user_b_id == b).first()
    match_id = int(match_row.id) if match_row else None

    their_read = (
        db.query(ThreadReadState)
        .filter(ThreadReadState.user_id == int(partner_user_id), ThreadReadState.partner_user_id == int(current_user.id))
        .first()
    )
    partner_user = db.query(User).filter(User.id == int(partner_user_id)).first()
    partner_last_read_at = their_read.last_read_at.isoformat() if their_read and their_read.last_read_at else None
    partner_last_active_at = (
        partner_user.last_active_at.isoformat()
        if partner_user and getattr(partner_user, "last_active_at", None)
        else None
    )

    return {
        "messages": payload,
        "match_id": match_id,
        "partner_last_read_at": partner_last_read_at,
        "partner_last_active_at": partner_last_active_at,
        "thread_has_more": len(rows) >= limit,
    }

def _message_to_json(msg: Message) -> dict:
    demo_flag = bool(getattr(msg, "is_demo_simulation", False))
    return {
        "id": msg.id,
        "sender_id": msg.sender_id,
        "receiver_id": msg.receiver_id,
        "content": msg.content,
        "is_read": bool(getattr(msg, "is_read", False)),
        "reply_to_message_id": getattr(msg, "reply_to_message_id", None),
        "voice_url": normalize_media_url(getattr(msg, "voice_url", None)),
        "voice_mime": getattr(msg, "voice_mime", None),
        "voice_duration_ms": getattr(msg, "voice_duration_ms", None),
        "is_demo_simulation": demo_flag,
        "is_demo": demo_flag,
        "ai_generated": bool(getattr(msg, "ai_generated", False)),
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


def _attach_reactions(db: Session, user_id: int, payload: list[dict]) -> list[dict]:
    ids = [p.get("id") for p in payload if p.get("id")]
    if not ids:
        return payload
    rows = db.query(MessageReaction).filter(MessageReaction.message_id.in_(ids)).all()
    counts: dict[int, dict[str, int]] = {}
    mine: dict[int, set[str]] = {}
    for r in rows:
        mid = int(r.message_id)
        emoji = (r.emoji or "").strip()
        if not emoji:
            continue
        counts.setdefault(mid, {})
        counts[mid][emoji] = int(counts[mid].get(emoji, 0)) + 1
        if int(r.user_id) == int(user_id):
            mine.setdefault(mid, set()).add(emoji)
    for p in payload:
        mid = p.get("id")
        if not mid:
            continue
        p["reactions"] = counts.get(int(mid), {})
        p["my_reactions"] = sorted(list(mine.get(int(mid), set())))
    return payload


@router.post("/ai-opener")
async def ai_conversation_opener(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create the first thread message using NEYRA copilot (empty human-human threads only)."""
    try:
        receiver_id = int(payload.get("receiver_id") or 0)
    except Exception:
        raise HTTPException(status_code=400, detail=api_error("chat.invalid_recipient"))
    if receiver_id < 1 or receiver_id == int(current_user.id):
        raise HTTPException(status_code=400, detail=api_error("chat.invalid_recipient"))
    if is_blocked(db, current_user.id, receiver_id):
        raise HTTPException(status_code=403, detail=api_error("chat.user_blocked"))
    if not users_are_matched(db, current_user.id, receiver_id):
        _log_unmatched_attempt(current_user.id, receiver_id, action="ai_opener")
        raise HTTPException(status_code=403, detail=_not_matched_detail())

    receiver = db.query(User).filter(User.id == receiver_id).first()
    receiver_profile = db.query(Profile).filter(Profile.user_id == receiver_id).first()
    if not receiver or not receiver_profile:
        raise HTTPException(status_code=400, detail=api_error("chat.invalid_recipient"))
    receiver_is_demo = is_demo_profile(receiver_profile, receiver)
    if receiver_is_demo:
        raise HTTPException(status_code=400, detail=api_error("chat.demo_disabled"))

    prior_n = (
        db.query(Message)
        .filter(
            or_(
                and_(Message.sender_id == current_user.id, Message.receiver_id == receiver_id),
                and_(Message.sender_id == receiver_id, Message.receiver_id == current_user.id),
            )
        )
        .limit(1)
        .count()
    )
    if prior_n > 0:
        raise HTTPException(status_code=400, detail=api_error("chat.ai_opener_not_empty"))

    my_profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    from app.application.use_cases.ai.wingman_openers import generate_openers

    locale_raw = payload.get("locale") or payload.get("language") or "en"
    locale = str(locale_raw).strip() or "en"
    suggestions: list = []
    try:
        suggestions = await generate_openers(my_profile, receiver_profile, allow_edgy_mode=False, locale=locale)
    except Exception:
        suggestions = []
    text = ""
    if suggestions and isinstance(suggestions, list):
        first = suggestions[0]
        if isinstance(first, dict):
            text = str(first.get("text") or first.get("content") or "").strip()
        elif isinstance(first, str):
            text = first.strip()
    if not text:
        o1, _, _ = three_demo_openers(locale)
        text = o1
    text = text.strip()
    if len(text) > 8000:
        text = text[:8000]

    msg = Message(sender_id=current_user.id, receiver_id=receiver_id, content=text, ai_generated=True)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    try:
        track_event(
            db,
            "ai_message_sent",
            user_id=current_user.id,
            payload={"receiver_id": receiver_id, "message_id": msg.id, "kind": "auto_opener"},
        )
    except Exception:
        pass
    wrapped = _attach_reactions(db, current_user.id, [_message_to_json(msg)])[0]
    try:
        await manager.send_to_user(int(current_user.id), {"type": "message", **wrapped})
        await manager.send_to_user(int(receiver_id), {"type": "message", **wrapped})
    except Exception:
        pass
    return {"message": wrapped}


@router.post("")
@router.post("/", include_in_schema=False)
async def send_message(
    payload: MessageCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    receiver_id = payload.receiver_id
    content = (payload.content or "").strip()
    context = payload.conversation_context
    voice_url = (payload.voice_url or "").strip() or None
    voice_mime = (payload.voice_mime or "").strip() or None
    voice_duration_ms = payload.voice_duration_ms
    idempotency_key = (payload.idempotency_key or "").strip() or None
    ui_transport_loc = resolve_http_ai_locale(request, db=db, user_id=int(current_user.id))

    receiver = db.query(User).filter(User.id == int(receiver_id)).first()
    receiver_profile = db.query(Profile).filter(Profile.user_id == int(receiver_id)).first()
    receiver_is_demo = is_demo_profile(receiver_profile, receiver)
    if receiver_is_demo and not is_demo_mode_enabled(db):
        raise HTTPException(status_code=403, detail=api_error("chat.demo_disabled"))
    if is_blocked(db, current_user.id, receiver_id):
        raise HTTPException(status_code=403, detail=api_error("chat.user_blocked"))
    if not users_are_matched(db, current_user.id, receiver_id):
        _log_unmatched_attempt(current_user.id, receiver_id, action="message_send")
        raise HTTPException(status_code=403, detail=_not_matched_detail())

    # Backend idempotency: same (user_id, partner_id, idempotency_key) returns existing message.
    if idempotency_key:
        try:
            r = get_redis()
            ik = f"msg:idemp:{int(current_user.id)}:{int(receiver_id)}:{idempotency_key}"
            existing_id_raw = r.get(ik)
            if existing_id_raw:
                try:
                    existing_id = int(existing_id_raw)
                except Exception:
                    existing_id = 0
                if existing_id > 0:
                    existing = db.query(Message).filter(Message.id == existing_id).first()
                    if existing:
                        return _attach_reactions(db, current_user.id, [_message_to_json(existing)])[0]
        except Exception:
            # Fail-open: idempotency should never block sending.
            pass

    # Messaging guard (server-only; silent for normal users). Fail-open if Redis unavailable.
    if content:
        try:
            r = get_redis()
            normalized = _norm_message_for_hash(content)
            h = _hash_text(normalized)

            # Identical-message burst prevention: same hash to multiple receivers in 2 minutes.
            recv_key = f"msg:dup:recvset:{current_user.id}:{h}"
            r.sadd(recv_key, str(receiver_id))
            r.expire(recv_key, 120)
            uniq_receivers = int(r.scard(recv_key) or 0)
            if uniq_receivers >= 4:
                track_event(
                    db,
                    "message_rate_limited",
                    user_id=current_user.id,
                    payload={"rule": "duplicate_burst", "window_s": 120},
                )
                raise HTTPException(status_code=429, detail=api_error("chat.rate_limit_personalize"))

            # Low-quality first-message rate limit (light): 1 new conversation per 60s.
            my_profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
            quality = compute_profile_quality(my_profile)
            if quality.quality_flag == "low_quality":
                prior = (
                    db.query(Message)
                    .filter(
                        or_(
                            and_(Message.sender_id == current_user.id, Message.receiver_id == receiver_id),
                            and_(Message.sender_id == receiver_id, Message.receiver_id == current_user.id),
                        )
                    )
                    .limit(1)
                    .count()
                    > 0
                )
                if not prior:
                    first_key = f"msg:first:{current_user.id}"
                    if not r.set(first_key, "1", nx=True, ex=60):
                        track_event(
                            db,
                            "message_rate_limited",
                            user_id=current_user.id,
                            payload={"rule": "low_quality_first_message", "window_s": 60},
                        )
                        raise HTTPException(status_code=429, detail=api_error("chat.rate_limit_new_chat"))
        except HTTPException:
            raise
        except Exception:
            pass
    try:
        if content:
            msg_risk = MessageRiskEvaluator.evaluate_message_risk(content, context, allow_edgy_mode=False)
            convo_quality = ConversationQualityEvaluator.evaluate_conversation_quality(context + [content])
            scam = ScamSignalDetector.detect_scam_signals(None, context + [content])
            my_profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
            profile_risk = ProfileRiskEvaluator.evaluate_profile_risk(my_profile)
            action, reasons = ActionPolicy().decide(
                PolicyInput(
                    message_risk=msg_risk.risk_score,
                    profile_risk=profile_risk.risk_score,
                    bot_probability=0,
                    scam_risk=scam.scam_risk,
                    conversation_quality=convo_quality["quality_score"],
                )
            )
            if action in {"hard_block", "soft_block"} or not msg_risk.allowed:
                track_event(
                    db,
                    "suspicious_message_detected",
                    user_id=current_user.id,
                    payload={"action": action, "reasons": reasons, **msg_risk.to_dict()},
                )
                if msg_risk.rewrite_suggestion:
                    return {
                        "status": "rewrite_suggested",
                        "rewrite_suggestion": msg_risk.rewrite_suggestion,
                        "flags": msg_risk.flags,
                        "quality_flags": msg_risk.quality_flags,
                    }
                logger.warning(
                    "message_hard_blocked sender_id=%s receiver_id=%s flags=%s",
                    current_user.id,
                    receiver_id,
                    list(msg_risk.flags or ()),
                )
                raise HTTPException(status_code=400, detail=api_error("chat.message_blocked"))
            if action in {"allow_with_warning", "allow_with_rewrite_suggestion"}:
                track_event(
                    db,
                    "cringe_warning_triggered",
                    user_id=current_user.id,
                    payload={"action": action, "reasons": reasons, **msg_risk.to_dict()},
                )
                if msg_risk.rewrite_suggestion:
                    return {
                        "status": "rewrite_suggested",
                        "rewrite_suggestion": msg_risk.rewrite_suggestion,
                        "flags": msg_risk.flags,
                        "quality_flags": msg_risk.quality_flags,
                    }

            # Legacy moderation (kept as a safety backstop for existing behavior).
            moderation = moderate_text(content)
            if not moderation["allowed"]:
                logger.warning(
                    "message_moderation_blocked sender_id=%s receiver_id=%s flags=%s",
                    current_user.id,
                    receiver_id,
                    list(moderation.get("flags") or ()),
                )
                raise HTTPException(status_code=400, detail=api_error("chat.moderation_blocked"))
        reply_to_message_id = payload.reply_to_message_id
        if reply_to_message_id:
            replied = db.query(Message).filter(Message.id == reply_to_message_id).first()
            if not replied:
                raise HTTPException(status_code=400, detail=api_error("chat.reply_not_found"))
            if not (
                (replied.sender_id == current_user.id and replied.receiver_id == receiver_id)
                or (replied.sender_id == receiver_id and replied.receiver_id == current_user.id)
            ):
                raise HTTPException(status_code=400, detail=api_error("chat.reply_invalid_target"))
        msg = Message(
            sender_id=current_user.id,
            receiver_id=receiver_id,
            content=content,
            reply_to_message_id=reply_to_message_id,
            voice_url=voice_url,
            voice_mime=voice_mime,
            voice_duration_ms=voice_duration_ms,
            ai_generated=False,
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        if idempotency_key:
            try:
                r = get_redis()
                ik = f"msg:idemp:{int(current_user.id)}:{int(receiver_id)}:{idempotency_key}"
                # Keep mapping long enough to cover reloads/back button loops.
                r.set(ik, str(int(msg.id)), ex=60 * 60 * 24, nx=True)
            except Exception:
                pass
        track_event(
            db,
            "message_sent",
            user_id=current_user.id,
            payload={
                "receiver_id": receiver_id,
                "message_id": msg.id,
                "receiver_is_demo": receiver_is_demo,
                "features": _message_features(content),
            },
        )
        wave = pop_ai_suggestion_wave(int(current_user.id), int(receiver_id))
        if wave:
            try:
                track_event(
                    db,
                    "user_replied_after_ai",
                    user_id=current_user.id,
                    payload={
                        "partner_user_id": int(receiver_id),
                        "message_id": msg.id,
                        **{k: v for k, v in wave.items() if k != "partner_user_id"},
                    },
                )
            except Exception:
                pass
        assist = payload.assist_meta
        if assist:
            try:
                am = assist.model_dump(exclude_none=True)
                common = {
                    "partner_user_id": int(receiver_id),
                    "message_id": msg.id,
                    "mode": str(am.get("mode") or ""),
                    "source": str(am.get("source") or ""),
                    "variant": am.get("variant"),
                    "brain_mode": am.get("brain_mode"),
                    "was_recommended": am.get("was_recommended"),
                    "conversation_stage": am.get("conversation_stage"),
                    "conversation_mode": am.get("conversation_mode"),
                    "edited_after_insert": am.get("edited_after_insert"),
                }
                if assist.kind == "rewrite":
                    track_event(db, "ai_rewrite_used", user_id=current_user.id, payload=common)
                else:
                    track_event(db, "ai_suggestion_used", user_id=current_user.id, payload=common)
            except Exception:
                pass
        # Trial trigger: user sent 3+ messages to the same chat partner.
        try:
            sent_count = (
                db.query(Message)
                .filter(Message.sender_id == current_user.id, Message.receiver_id == receiver_id)
                .count()
            )
            if int(sent_count or 0) == 3:
                maybe_start_premium_trial(db, user_id=int(current_user.id), reason="sent_3_messages")
        except Exception:
            pass
        if not receiver_is_demo and not bool(getattr(current_user, "is_demo", False)):
            publish_event("message_sent", {"sender_id": current_user.id, "receiver_id": receiver_id, "message_id": msg.id})
        out = _attach_reactions(db, current_user.id, [_message_to_json(msg)])[0]
        demo_reply_out = None
        demo_reply_scheduled = False
        expected_reply_delay_seconds = 0
        if receiver_is_demo:
            if bool(getattr(settings, "DEMO_BOT_CHAT_ENABLED", True)):
                expected_reply_delay_seconds = max(0, int(getattr(settings, "DEMO_BOT_REPLY_DELAY_SECONDS", 2) or 0))
                if not is_demo_live_enabled(db):
                    expected_reply_delay_seconds = 0
                note_real_user_message_to_demo(
                    db,
                    receiver_id,
                    current_user.id,
                    trigger_message_id=int(msg.id),
                )
                demo_reply_scheduled = True
                # Dev UX: deliver near-immediate demo reply without waiting for external scheduler.
                env = str(getattr(settings, "ENV", "") or "").strip().lower()
                delay_s = int(getattr(settings, "DEMO_BOT_REPLY_DELAY_SECONDS", 2) or 0)
                if env in {"development", "dev"} or delay_s <= 1:
                    run_demo_behavior_tick(db)
                    latest_demo = (
                        db.query(Message)
                        .filter(Message.sender_id == receiver_id, Message.receiver_id == current_user.id)
                        .order_by(Message.created_at.desc())
                        .first()
                    )
                    if latest_demo and latest_demo.is_demo_simulation:
                        demo_reply_out = _attach_reactions(db, current_user.id, [_message_to_json(latest_demo)])[0]
                        demo_reply_out["content"] = coerce_demo_partner_message_body(
                            raw_db=str(demo_reply_out.get("content") or ""),
                            locale=ui_transport_loc,
                            message_id=int(latest_demo.id),
                            sender_is_demo_bot=True,
                            route="POST /messages/demo_tick",
                        )
            else:
                prior_demo_replies = (
                    db.query(Message)
                    .filter(Message.sender_id == receiver_id, Message.receiver_id == current_user.id)
                    .count()
                )
                reply_text = build_demo_reply(receiver_profile, content or "[voice message]", context)
                demo_msg = Message(
                    sender_id=receiver_id,
                    receiver_id=current_user.id,
                    content=reply_text,
                    is_demo_simulation=True,
                )
                db.add(demo_msg)
                db.commit()
                db.refresh(demo_msg)
                if int(prior_demo_replies or 0) == 0:
                    track_event(db, "demo_chat_started", user_id=current_user.id, payload={"partner_user_id": receiver_id, "source": "message_send"})
                demo_reply_out = _attach_reactions(db, current_user.id, [_message_to_json(demo_msg)])[0]
                demo_reply_out["content"] = coerce_demo_partner_message_body(
                    raw_db=str(demo_reply_out.get("content") or ""),
                    locale=ui_transport_loc,
                    message_id=int(demo_msg.id),
                    sender_is_demo_bot=True,
                    route="POST /messages/sync_demo_reply",
                )
        # Best-effort realtime fanout to connected websocket clients.
        try:
            await manager.send_to_user(current_user.id, {"type": "message", **out})
            if not receiver_is_demo:
                await manager.send_to_user(receiver_id, {"type": "message", **out})
            if demo_reply_out:
                await manager.send_to_user(current_user.id, {"type": "message", **demo_reply_out})
        except Exception:
            pass
        if demo_reply_out:
            return {
                "message": out,
                "demo_reply": demo_reply_out,
                "demo_chat_label": localized_demo_chat_banner(ui_transport_loc),
                "demo_reply_scheduled": True,
                "demo_partner": True,
                "expected_reply_delay_seconds": int(max(0, expected_reply_delay_seconds)),
            }
        if receiver_is_demo:
            return {
                "message": out,
                "demo_chat_label": localized_demo_chat_banner(ui_transport_loc),
                "demo_reply_scheduled": bool(demo_reply_scheduled),
                "demo_partner": True,
                "expected_reply_delay_seconds": int(max(0, expected_reply_delay_seconds)),
            }
        return out
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "message_send_failed sender_id=%s receiver_id=%s",
            current_user.id,
            receiver_id,
        )
        raise HTTPException(status_code=500, detail=api_error("chat.send_failed")) from None


@router.post("/{message_id}/reactions")
def react_to_message(
    message_id: int,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    emoji = str(payload.get("emoji") or "").strip()
    if emoji not in {"❤️", "👍", "😂"}:
        raise HTTPException(status_code=400, detail=api_error("chat.reaction_invalid"))
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail=api_error("chat.message_not_found"))
    other_id = msg.receiver_id if msg.sender_id == current_user.id else msg.sender_id
    if is_blocked(db, current_user.id, other_id):
        raise HTTPException(status_code=403, detail=api_error("chat.user_blocked"))
    if not users_are_matched(db, current_user.id, other_id):
        _log_unmatched_attempt(current_user.id, other_id, action="message_react")
        raise HTTPException(status_code=403, detail=_not_matched_detail())
    existing = (
        db.query(MessageReaction)
        .filter(
            MessageReaction.message_id == message_id,
            MessageReaction.user_id == current_user.id,
            MessageReaction.emoji == emoji,
        )
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()
        return {"ok": True, "status": "removed"}
    r = MessageReaction(message_id=message_id, user_id=current_user.id, emoji=emoji)
    db.add(r)
    db.commit()
    return {"ok": True, "status": "added"}
