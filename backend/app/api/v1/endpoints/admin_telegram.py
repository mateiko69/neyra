"""
Telegram admin bot proxies: call existing /ai/* endpoint implementations as a chosen
viewer user (Impulse match + monetization logic unchanged). Requires admin JWT or
X-Admin-Service-Token via get_admin_actor.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette.requests import Request as StarletteRequest

from app.api.deps import get_admin_actor, get_db
from app.api.v1.endpoints import admin as admin_ep
from app.api.v1.endpoints import ai as ai_ep
from app.core.config import settings
from app.models.message import Message
from app.models.user import User
from app.schemas.ai_wingman import (
    ChatCopilotRequest,
    ImproveReplyRequest,
    MeetingReadinessRequest,
    StartStrategyRequest,
    TimedRepliesRequest,
)
from app.services.analytics import track_event

router = APIRouter()

_ALLOWED_TRACK = frozenset(
    {"ai_used", "ai_suggestion_used", "order_created", "shipment_created", "ai_limit_hit"}
)

_MEETING_READY_NOTICE_THRESHOLD = 60


def _synthetic_request(*, locale: str | None) -> StarletteRequest:
    headers: list[tuple[bytes, bytes]] = []
    if locale:
        headers.append((b"x-locale", str(locale).encode("utf-8")))
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/ai/chat-copilot",
        "raw_path": b"/api/v1/ai/chat-copilot",
        "root_path": "",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 0),
        "server": ("127.0.0.1", 8000),
    }
    return StarletteRequest(scope)


def _load_viewer(db: Session, viewer_user_id: int) -> User:
    u = db.query(User).filter(User.id == int(viewer_user_id)).first()
    if not u:
        raise HTTPException(status_code=404, detail="viewer_user_id not found")
    return u


def _messages_for_pair(db: Session, viewer_id: int, partner_id: int, *, max_msgs: int = 50) -> list[dict]:
    rows = (
        db.query(Message)
        .filter(
            ((Message.sender_id == int(viewer_id)) & (Message.receiver_id == int(partner_id)))
            | ((Message.sender_id == int(partner_id)) & (Message.receiver_id == int(viewer_id)))
        )
        .order_by(Message.created_at.desc())
        .limit(int(max_msgs))
        .all()
    )
    rows.reverse()
    chat: list[dict] = []
    for m in rows:
        role = "me" if int(m.sender_id) == int(viewer_id) else "them"
        text = (m.content or "").strip()
        if not text and getattr(m, "voice_url", None):
            text = "[voice message]"
        if not text:
            continue
        chat.append({"role": role, "text": text})
    return ai_ep._format_chat_context(chat, max_messages=int(max_msgs))


def _tag_runtime(ok: bool) -> str:
    return "[runtime_verified]" if ok else "[not_verified]"


def _tag_ai(provider_ok: bool, enabled: bool) -> str:
    if not enabled:
        return "[partial]"
    return "[runtime_verified]" if provider_ok else "[not_verified]"


@router.post("/telegram/ai/chat-copilot")
async def admin_telegram_chat_copilot(
    body: dict = Body(default_factory=dict),
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    _ = admin_actor
    try:
        viewer_user_id = int(body.get("viewer_user_id") or 0)
    except Exception:
        viewer_user_id = 0
    if viewer_user_id < 1:
        raise HTTPException(status_code=400, detail="viewer_user_id required")
    try:
        partner_user_id = int(body.get("partner_user_id") or 0)
    except Exception:
        partner_user_id = 0
    if partner_user_id < 1:
        raise HTTPException(status_code=400, detail="partner_user_id required")

    u = _load_viewer(db, viewer_user_id)
    loc = str(body.get("locale") or "").strip() or None
    req = ChatCopilotRequest(
        partner_user_id=int(partner_user_id),
        mode=body.get("mode"),
        user_selected_style=body.get("user_selected_style"),
        locale=loc,
    )
    request = _synthetic_request(locale=loc)
    return await ai_ep.chat_copilot(req, request=request, current_user=u, db=db)


@router.post("/telegram/ai/timed-replies")
async def admin_telegram_timed_replies(
    body: dict = Body(default_factory=dict),
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    _ = admin_actor
    try:
        viewer_user_id = int(body.get("viewer_user_id") or 0)
    except Exception:
        viewer_user_id = 0
    if viewer_user_id < 1:
        raise HTTPException(status_code=400, detail="viewer_user_id required")
    try:
        partner_user_id = int(body.get("partner_user_id") or 0)
    except Exception:
        partner_user_id = 0
    if partner_user_id < 1:
        raise HTTPException(status_code=400, detail="partner_user_id required")

    u = _load_viewer(db, viewer_user_id)
    msgs = body.get("messages")
    if not isinstance(msgs, list) or not msgs:
        msgs = _messages_for_pair(db, viewer_user_id, partner_user_id)
    req = TimedRepliesRequest(
        messages=msgs,
        nudge_type=str(body.get("nudge_type") or "now"),
        interest_stage=body.get("interest_stage"),
        mutuality_score=body.get("mutuality_score"),
        locale=body.get("locale") or "en",
        language_hint=body.get("language_hint"),
        last_message_at=body.get("last_message_at"),
        who_sent_last=body.get("who_sent_last"),
    )
    loc = str(body.get("locale") or "").strip() or None
    request = _synthetic_request(locale=loc)
    return await ai_ep.timed_replies(req, request=request, current_user=u, db=db)


@router.post("/telegram/ai/start-strategy")
async def admin_telegram_start_strategy(
    body: dict = Body(default_factory=dict),
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    _ = admin_actor
    try:
        viewer_user_id = int(body.get("viewer_user_id") or 0)
    except Exception:
        viewer_user_id = 0
    if viewer_user_id < 1:
        raise HTTPException(status_code=400, detail="viewer_user_id required")
    try:
        partner_user_id = int(body.get("partner_user_id") or 0)
    except Exception:
        partner_user_id = 0
    if partner_user_id < 1:
        raise HTTPException(status_code=400, detail="partner_user_id required")

    u = _load_viewer(db, viewer_user_id)
    raw_msgs = body.get("messages")
    messages: list[str] = []
    if isinstance(raw_msgs, list):
        messages = [str(x) for x in raw_msgs[:3]]
    req = StartStrategyRequest(
        partner_user_id=int(partner_user_id),
        messages=messages,
        locale=body.get("locale"),
        language=body.get("language"),
    )
    return await ai_ep.start_strategy(req, current_user=u, db=db)


@router.post("/telegram/ai/meeting-ready")
async def admin_telegram_meeting_ready(
    body: dict = Body(default_factory=dict),
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    _ = admin_actor
    try:
        viewer_user_id = int(body.get("viewer_user_id") or 0)
    except Exception:
        viewer_user_id = 0
    if viewer_user_id < 1:
        raise HTTPException(status_code=400, detail="viewer_user_id required")
    try:
        partner_user_id = int(body.get("partner_user_id") or 0)
    except Exception:
        partner_user_id = 0
    if partner_user_id < 1:
        raise HTTPException(status_code=400, detail="partner_user_id required")

    u = _load_viewer(db, viewer_user_id)
    msgs = body.get("messages")
    if not isinstance(msgs, list) or not msgs:
        msgs = _messages_for_pair(db, viewer_user_id, partner_user_id)
    req = MeetingReadinessRequest(
        messages=msgs,
        partner_user_id=int(partner_user_id),
        thread_id=body.get("thread_id"),
        locale=str(body.get("locale") or "en"),
        city=body.get("city"),
        conversation_stats=body.get("conversation_stats"),
        mark_shown=bool(body.get("mark_shown")),
        response_time_seconds=body.get("response_time_seconds"),
        who_initiates=body.get("who_initiates"),
        avg_message_length=body.get("avg_message_length"),
    )
    out = await ai_ep.meeting_ready(req, current_user=u, db=db)
    # Non-breaking enrichment for Telegram UI (JSON extra keys; same core fields as /ai/meeting-ready).
    try:
        score = int(getattr(out, "readiness_score", 0) or 0)
    except Exception:
        score = 0
    warm = score > _MEETING_READY_NOTICE_THRESHOLD
    if hasattr(out, "model_dump"):
        data = out.model_dump()
    elif hasattr(out, "dict"):
        data = out.dict()  # type: ignore[call-arg]
    else:
        data = dict(out)  # type: ignore[arg-type]
    data["telegram_closer_hint"] = bool(warm)
    data["telegram_threshold"] = int(_MEETING_READY_NOTICE_THRESHOLD)
    return data


@router.post("/telegram/ai/improve-reply")
async def admin_telegram_improve_reply(
    body: dict = Body(default_factory=dict),
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    _ = admin_actor
    try:
        viewer_user_id = int(body.get("viewer_user_id") or 0)
    except Exception:
        viewer_user_id = 0
    if viewer_user_id < 1:
        raise HTTPException(status_code=400, detail="viewer_user_id required")

    u = _load_viewer(db, viewer_user_id)
    req = ImproveReplyRequest(
        draft=str(body.get("draft") or ""),
        conversation_context=body.get("conversation_context") or [],
        user_style=str(body.get("user_style") or "chill"),
        allow_edgy_mode=bool(body.get("allow_edgy_mode")),
        mode=body.get("mode"),
        locale=body.get("locale"),
        language_hint=body.get("language_hint"),
    )
    loc = str(body.get("locale") or "").strip() or None
    request = _synthetic_request(locale=loc)
    return await ai_ep.wingman_improve_reply(req, request=request, current_user=u, db=db)


@router.post("/telegram/analytics/track")
def admin_telegram_analytics_track(
    body: dict = Body(default_factory=dict),
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    _ = admin_actor
    name = str(body.get("name") or "").strip()
    if name not in _ALLOWED_TRACK:
        raise HTTPException(status_code=400, detail="unsupported analytics event")
    uid = body.get("user_id")
    try:
        user_id = int(uid) if uid is not None and str(uid).strip() != "" else None
    except Exception:
        user_id = None
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    meta = {**payload, "source": "telegram_admin_bot"}
    if body.get("telegram_admin_id") is not None:
        meta["telegram_admin_id"] = body.get("telegram_admin_id")
    track_event(db, name, user_id=user_id, payload=meta)
    return {"ok": True}


@router.get("/telegram/diagnostics")
def admin_telegram_diagnostics(
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    base = admin_ep.system_doctor(admin_actor=admin_actor, db=db)
    if not isinstance(base, dict):
        base = {}

    api_ok = base.get("api_status") == "ok"
    db_ok = base.get("database_status") == "ok"
    gem_status = str(base.get("gemini_status") or "")
    prov = str(getattr(settings, "AI_PROVIDER", "") or "").strip().lower()
    has_key = bool(str(getattr(settings, "GEMINI_API_KEY", "") or "").strip())
    ai_enabled = bool(getattr(settings, "ENABLE_AI_SUGGESTIONS", False))
    provider_runtime_ok = prov == "gemini" and has_key and gem_status == "ok"

    lines: list[str] = [
        f"API {_tag_runtime(api_ok)} — http handler reachable",
        f"DB {_tag_runtime(db_ok)} — SELECT 1 / alembic",
        f"AI provider {_tag_ai(provider_runtime_ok, ai_enabled)} — provider={prov or 'n/a'}, gemini={gem_status}",
        (
            f"[static_verified] — ENABLE_AI_SUGGESTIONS={ai_enabled}, AI_PROVIDER={prov or 'n/a'}, "
            f"GEMINI_CHAT_MODEL={getattr(settings, 'GEMINI_CHAT_MODEL', '') or 'n/a'}"
        ),
    ]

    errs = base.get("last_10_errors")
    last5: list[Any] = []
    if isinstance(errs, list):
        last5 = errs[:5]

    modes = {
        "premium_features": bool(getattr(settings, "ENABLE_PREMIUM_FEATURES", False)),
        "ai_suggestions": ai_enabled,
        "ai_provider": prov or None,
    }

    return {
        **base,
        "telegram_diagnostic_lines": lines,
        "telegram_active_modes": modes,
        "telegram_last_errors": last5,
        "telegram_error_tags": "[runtime_verified]" if isinstance(errs, list) else "[partial]",
    }
