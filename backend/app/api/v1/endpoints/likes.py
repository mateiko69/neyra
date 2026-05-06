from __future__ import annotations

import logging
from datetime import UTC, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.domain.matching.compatibility_engine import CompatibilityEngine
from app.models.incoming_like_hide import IncomingLikeHide
from app.models.match import Match
from app.models.profile import Profile
from app.models.swipe import Swipe
from app.models.user import User
from app.services.safety import blocked_user_ids
from app.services.monetization.subscription_service import SubscriptionService
from app.services.monetization.access import MonetizationAccess
from app.utils.media_urls import normalize_photo_url
from app.services.trust.verification_state import is_verified_profile
from app.api.v1.endpoints.swipes import create_swipe as create_swipe_endpoint

router = APIRouter()

_log = logging.getLogger(__name__)

MAX_INCOMING_SCAN = 800


def _is_premium(user: User) -> bool:
    until = getattr(user, "premium_until", None)
    if until is None:
        return False
    try:
        return until > datetime.now(UTC)
    except Exception:
        return False


def _utc_day_start(now: datetime | None = None) -> datetime:
    n = now if now is not None else datetime.now(UTC)
    if n.tzinfo is None:
        n = n.replace(tzinfo=UTC)
    return n.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _as_utc_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(UTC)


def _distance_km(me: Profile | None, other: Profile | None) -> int | None:
    my_city = (getattr(me, "city", "") or "").strip().lower()
    other_city = (getattr(other, "city", "") or "").strip().lower()
    if not other_city:
        return None
    if my_city and my_city == other_city:
        return 1
    return 25


def _hint_key(match_score: int, other: Profile | None) -> str:
    bio_ok = bool((getattr(other, "bio", "") or "").strip())
    interests_ok = bool((getattr(other, "interests", "") or "").strip())
    if match_score >= 86:
        return "likes.hint.strongCompat"
    if match_score >= 78:
        return "likes.hint.highMatch"
    if bio_ok and interests_ok:
        return "likes.hint.similarVibe"
    return "likes.hint.replyLikely"


def _mask_preview_name(display_name: str) -> str:
    s = (display_name or "").strip()
    if not s:
        return "S****"
    first = s[0].upper()
    return f"{first}****"


def _hidden_admirer_ids(db: Session, viewer_user_id: int) -> set[int]:
    rows = (
        db.query(IncomingLikeHide.admirer_user_id)
        .filter(IncomingLikeHide.viewer_user_id == viewer_user_id)
        .all()
    )
    return {int(r[0]) for r in rows if r and r[0] is not None}


def _dedupe_swipes_latest_per_swiper(rows: list[Swipe]) -> list[Swipe]:
    seen: set[int] = set()
    out: list[Swipe] = []
    for swipe in rows:
        sid = int(swipe.swiper_id)
        if sid in seen:
            continue
        seen.add(sid)
        out.append(swipe)
    return out


def _eligible_incoming_swipes(
    db: Session,
    current_user_id: int,
    blocked: set[int],
    hidden_ids: set[int],
    *,
    max_scan: int = MAX_INCOMING_SCAN,
) -> list[Swipe]:
    base = (
        db.query(Swipe)
        .filter(Swipe.target_user_id == current_user_id)
        .filter(Swipe.liked == True)  # noqa: E712
        .order_by(Swipe.created_at.desc())
    )
    rows_raw = base.limit(max_scan).all()
    rows = _dedupe_swipes_latest_per_swiper(rows_raw)
    eligible: list[Swipe] = []
    for swipe in rows:
        admirer_id = int(getattr(swipe, "swiper_id", 0) or 0)
        if admirer_id <= 0 or admirer_id in blocked or admirer_id in hidden_ids:
            continue
        a, b = sorted([current_user_id, admirer_id])
        existing_match = (
            db.query(Match)
            .filter(Match.user_a_id == a)
            .filter(Match.user_b_id == b)
            .first()
        )
        if existing_match:
            continue
        admirer_user = db.query(User).filter(User.id == admirer_id).first()
        if not admirer_user or bool(getattr(admirer_user, "is_deleted", False)):
            continue
        admirer_profile = db.query(Profile).filter(Profile.user_id == admirer_id).first()
        if not admirer_profile:
            continue
        eligible.append(swipe)
    return eligible


def _premium_flags(db: Session, current_user: User) -> tuple[bool, bool]:
    subs = SubscriptionService()
    access = MonetizationAccess()
    plan = subs.get_active_plan(db, current_user.id)
    can_see = access.check_access(db, current_user.id, "see_who_liked_you")["allowed"]
    priority = access.check_access(db, current_user.id, "likes_priority_high_match")["allowed"]
    premium = plan in {"premium", "premium_plus"} or can_see or _is_premium(current_user)
    return premium, priority


def _build_like_rows(
    db: Session,
    current_user: User,
    swipes: list[Swipe],
    *,
    premium: bool,
    priority: bool,
    limit: int,
) -> list[dict]:
    me_profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    engine = CompatibilityEngine()
    out: list[dict] = []
    for swipe in swipes[:limit]:
        admirer_id = int(swipe.swiper_id)
        admirer_profile = db.query(Profile).filter(Profile.user_id == admirer_id).first()
        if not admirer_profile:
            continue
        admirer_name = (getattr(admirer_profile, "display_name", "") or "").strip()
        raw_photos = (getattr(admirer_profile, "photo_urls", "") or "").strip()
        photo_url = None
        if raw_photos:
            parts = [x.strip() for x in raw_photos.split(",") if x.strip()]
            if parts:
                photo_url = normalize_photo_url(parts[0], demo_profile_gender=getattr(admirer_profile, "gender", None)) or None
        comp = engine.evaluate(me_profile, admirer_profile)
        match_score = max(0, min(100, int(getattr(comp, "compatibility_score", 0) or 0)))
        out.append(
            {
                "userId": str(admirer_id),
                "displayName": admirer_name if premium else "",
                "age": getattr(admirer_profile, "age", None),
                "city": (getattr(admirer_profile, "city", "") or "").strip(),
                "distanceKm": _distance_km(me_profile, admirer_profile),
                "matchScore": match_score,
                "hasPhoto": bool(photo_url),
                "photoUrl": photo_url,
                "hintKey": _hint_key(match_score, admirer_profile),
            }
        )
    if priority and len(out) > 1:
        out = sorted(out, key=lambda r: int(r.get("matchScore") or 0), reverse=True)
    total_waiting = len(swipes)
    for idx, row in enumerate(out):
        if premium:
            row["previewLevel"] = "visible"
        else:
            row["previewLevel"] = "partial" if idx == 0 and total_waiting > 0 else "blur"
    return out


class LikeUserBody(BaseModel):
    user_id: int = Field(..., ge=1)


class LikesRespondBody(BaseModel):
    user_id: int = Field(..., ge=1)
    action: str = Field(..., min_length=1, max_length=8)  # like|pass


@router.get("/received")
def likes_received(
    limit: int = 6,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    limit = max(1, min(int(limit or 6), 12))
    blocked = blocked_user_ids(db, current_user.id)
    hidden = _hidden_admirer_ids(db, current_user.id)
    eligible = _eligible_incoming_swipes(db, current_user.id, blocked, hidden)
    waiting_count = len(eligible)
    premium, priority = _premium_flags(db, current_user)
    likes_received_rows = _build_like_rows(
        db, current_user, eligible, premium=premium, priority=priority, limit=limit
    )
    return {"count": waiting_count, "likesReceived": likes_received_rows}


@router.get("/incoming")
def likes_incoming(
    limit: int = 24,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Incoming likes for the premium Likes screen (snake_case fields)."""
    limit = max(1, min(int(limit or 24), 48))
    blocked = blocked_user_ids(db, current_user.id)
    hidden = _hidden_admirer_ids(db, current_user.id)
    eligible = _eligible_incoming_swipes(db, current_user.id, blocked, hidden)
    waiting_count = len(eligible)
    day_start = _utc_day_start()
    today_count = sum(
        1 for s in eligible if (ca := _as_utc_aware(s.created_at)) is not None and ca >= day_start
    )
    premium, priority = _premium_flags(db, current_user)
    me_profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    engine = CompatibilityEngine()
    ordered = eligible
    if priority and len(ordered) > 1:
        scored: list[tuple[Swipe, int]] = []
        for swipe in ordered:
            aid = int(swipe.swiper_id)
            other = db.query(Profile).filter(Profile.user_id == aid).first()
            if not other:
                continue
            comp = engine.evaluate(me_profile, other)
            scored.append((swipe, max(0, min(100, int(getattr(comp, "compatibility_score", 0) or 0)))))
        ordered = [p[0] for p in sorted(scored, key=lambda x: x[1], reverse=True)]

    items: list[dict] = []
    for swipe in ordered[:limit]:
        admirer_id = int(swipe.swiper_id)
        admirer_profile = db.query(Profile).filter(Profile.user_id == admirer_id).first()
        if not admirer_profile:
            continue
        admirer_name = (getattr(admirer_profile, "display_name", "") or "").strip()
        raw_photos = (getattr(admirer_profile, "photo_urls", "") or "").strip()
        photo_url = None
        if raw_photos:
            parts = [x.strip() for x in raw_photos.split(",") if x.strip()]
            if parts:
                photo_url = normalize_photo_url(parts[0], demo_profile_gender=getattr(admirer_profile, "gender", None)) or None
        dist = _distance_km(me_profile, admirer_profile)
        preview_name = admirer_name if premium else _mask_preview_name(admirer_name)
        items.append(
            {
                "user_id": admirer_id,
                "photo_url": photo_url,
                "distance": dist,
                "preview_name": preview_name,
            }
        )

    viewer_verified = bool(me_profile and is_verified_profile(me_profile))
    return {
        "waiting_count": waiting_count,
        "today_count": today_count,
        "is_premium": premium,
        "viewer_is_verified": viewer_verified,
        "items": items,
    }


@router.post("/hide")
def likes_hide(
    body: LikeUserBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    admirer_id = int(body.user_id)
    if admirer_id == current_user.id:
        raise HTTPException(status_code=400, detail="invalid_user")
    blocked = blocked_user_ids(db, current_user.id)
    if blocked and admirer_id in blocked:
        raise HTTPException(status_code=400, detail="blocked")
    existing = (
        db.query(Swipe)
        .filter(Swipe.swiper_id == admirer_id)
        .filter(Swipe.target_user_id == current_user.id)
        .filter(Swipe.liked == True)  # noqa: E712
        .first()
    )
    if not existing:
        raise HTTPException(status_code=404, detail="like_not_found")
    dup = (
        db.query(IncomingLikeHide)
        .filter(IncomingLikeHide.viewer_user_id == current_user.id)
        .filter(IncomingLikeHide.admirer_user_id == admirer_id)
        .first()
    )
    if not dup:
        db.add(IncomingLikeHide(viewer_user_id=current_user.id, admirer_user_id=admirer_id))
        db.commit()
    return {"ok": True}


@router.post("/reveal")
def likes_reveal(
    body: LikeUserBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    admirer_id = int(body.user_id)
    if admirer_id == current_user.id:
        raise HTTPException(status_code=400, detail="invalid_user")
    premium, _ = _premium_flags(db, current_user)
    existing = (
        db.query(Swipe)
        .filter(Swipe.swiper_id == admirer_id)
        .filter(Swipe.target_user_id == current_user.id)
        .filter(Swipe.liked == True)  # noqa: E712
        .first()
    )
    if not existing:
        raise HTTPException(status_code=404, detail="like_not_found")
    if not premium:
        return {"ok": False, "requires_premium": True, "profile_path": None}
    return {"ok": True, "requires_premium": False, "profile_path": f"/people/{admirer_id}"}


@router.post("/respond")
def likes_respond(
    body: LikesRespondBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Respond to an incoming like without relying on Discover:
    - like: create swipe like back (may create match)
    - pass: hide incoming like
    """
    admirer_id = int(body.user_id)
    action = str(body.action or "").strip().lower()
    if admirer_id == int(current_user.id):
        raise HTTPException(status_code=400, detail="invalid_user")
    existing = (
        db.query(Swipe)
        .filter(Swipe.swiper_id == admirer_id)
        .filter(Swipe.target_user_id == current_user.id)
        .filter(Swipe.liked == True)  # noqa: E712
        .first()
    )
    if not existing:
        raise HTTPException(status_code=404, detail="like_not_found")
    if action in {"pass", "nope"}:
        # Treat pass as UI hide (does not block chat/matches system-wide).
        dup = (
            db.query(IncomingLikeHide)
            .filter(IncomingLikeHide.viewer_user_id == current_user.id)
            .filter(IncomingLikeHide.admirer_user_id == admirer_id)
            .first()
        )
        if not dup:
            db.add(IncomingLikeHide(viewer_user_id=current_user.id, admirer_user_id=admirer_id))
            db.commit()
        return {"ok": True, "matched": False, "message": "Passed"}
    if action != "like":
        raise HTTPException(status_code=400, detail="invalid_action")

    # Reuse the canonical swipe creation logic (limits, match creation, demo behavior).
    try:
        out = create_swipe_endpoint({"target_user_id": admirer_id, "liked": True}, current_user=current_user, db=db)
    except HTTPException:
        raise
    except Exception:
        _log.exception(
            "likes_respond_swipe_failed admirer_id=%s viewer_id=%s",
            admirer_id,
            getattr(current_user, "id", None),
        )
        raise HTTPException(status_code=503, detail="likes_respond_unavailable") from None
    # Normalize response to the Likes flow contract.
    obj = out if isinstance(out, dict) else {}
    conversation_id = None
    if obj.get("matched"):
        conv_raw = obj.get("conversation_id")
        try:
            conversation_id = int(conv_raw) if conv_raw is not None else int(admirer_id)
        except (TypeError, ValueError):
            conversation_id = int(admirer_id)
    return {
        "ok": True,
        "matched": bool(obj.get("matched")),
        "match_id": obj.get("match_id"),
        "conversation_id": conversation_id,
        "partner_user_id": int(admirer_id) if obj.get("matched") else None,
        "chat_url": obj.get("chat_url"),
        "message": obj.get("message") or "OK",
    }


def count_eligible_incoming_likes(db: Session, viewer_user_id: int) -> int:
    """Count incoming likes visible in Likes UI (excludes blocked, hidden, already matched)."""
    blocked = blocked_user_ids(db, viewer_user_id)
    hidden = _hidden_admirer_ids(db, viewer_user_id)
    return len(_eligible_incoming_swipes(db, viewer_user_id, blocked, hidden))
