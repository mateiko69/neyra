from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from datetime import UTC, datetime

from sqlalchemy import func
from app.api.deps import get_db, get_current_user
from app.api.api_errors import api_error
from app.models.user import User
from app.models.swipe import Swipe
from app.models.match import Match
from app.models.profile import Profile
from app.services.analytics import track_event
from app.services.events import publish_event
from app.services.safety import is_blocked
from app.services.ai.cache import bump_user_cache_version, cache_get, cache_set, cache_key
from sqlalchemy import or_
from app.services.demo_behavior import run_demo_behavior_tick, schedule_demo_first_message_maybe
from app.services.demo_mode import is_demo_mode_enabled, is_demo_profile, is_demo_user
from app.services.monetization.subscription_service import SubscriptionService
from app.services.matching import create_match_if_mutual

router = APIRouter()

FREE_LIKE_LIMIT_PER_DAY = 25
FREE_UNDO_LIMIT_PER_DAY = 1


def _utc_day_sig(now: datetime | None = None) -> str:
    return _utc_day_start(now).date().isoformat()


def _store_last_swipe(user_id: int, *, target_user_id: int, liked: bool):
    """Best-effort cache for undo (short TTL)."""
    try:
        ck = cache_key("last_swipe", {"user_id": int(user_id)})
        cache_set(
            ck,
            {
                "target_user_id": int(target_user_id),
                "liked": bool(liked),
                "ts": datetime.now(UTC).isoformat(),
            },
            ttl_s=20 * 60,
        )
    except Exception:
        pass


def _partner_payload(db: Session, target_user_id: int) -> dict:
    profile = db.query(Profile).filter(Profile.user_id == int(target_user_id)).first()
    if not profile:
        return {"user_id": int(target_user_id)}
    return {
        "user_id": int(target_user_id),
        "display_name": str(getattr(profile, "display_name", "") or ""),
        "photo_urls": [x.strip() for x in str(getattr(profile, "photo_urls", "") or "").split(",") if x.strip()],
    }

def _utc_day_start(now: datetime | None = None) -> datetime:
    n = now if now is not None else datetime.now(UTC)
    if n.tzinfo is None:
        n = n.replace(tzinfo=UTC)
    return n.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

@router.post("")
@router.post("/", include_in_schema=False)
def create_swipe(payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    target_user_id = int(payload["target_user_id"])
    liked = bool(payload["liked"])
    super_like = bool(payload.get("super_like"))
    # Free tier: hard limit likes/day (Tinder-style). Premium: unlimited.
    try:
        plan = SubscriptionService().get_active_plan(db, int(current_user.id))
    except Exception:
        plan = "free"
    if liked and plan not in {"premium", "premium_plus"}:
        since = _utc_day_start()
        used = (
            db.query(func.count(Swipe.id))
            .filter(Swipe.swiper_id == int(current_user.id))
            .filter(Swipe.liked == True)  # noqa: E712
            .filter(Swipe.created_at >= since)
            .scalar()
        )
        if int(used or 0) >= FREE_LIKE_LIMIT_PER_DAY:
            raise HTTPException(status_code=402, detail=api_error("paywall.likes_limit", max=FREE_LIKE_LIMIT_PER_DAY))
    if target_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot swipe yourself")
    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user or bool(getattr(target_user, "is_deleted", False)):
        raise HTTPException(status_code=404, detail="User not found")
    target = db.query(Profile).filter(Profile.user_id == target_user_id).first()
    current_profile = db.query(Profile).filter(Profile.user_id == int(current_user.id)).first()
    is_onboarding_completed = bool(getattr(current_profile, "onboarding_completed", False))
    target_is_demo = is_demo_user(target_user, target)
    if target_is_demo and not is_demo_mode_enabled(db):
        raise HTTPException(status_code=403, detail="Demo mode is disabled")
    if is_blocked(db, current_user.id, target_user_id):
        raise HTTPException(status_code=403, detail="User is blocked")
    existing = db.query(Swipe).filter(Swipe.swiper_id == current_user.id, Swipe.target_user_id == target_user_id).first()
    if existing:
        # Idempotent behavior: return current matched status instead of 400.
        if liked and not bool(getattr(existing, "liked", False)):
            existing.liked = True
            db.add(existing)
            db.commit()
        elif (not liked) and bool(getattr(existing, "liked", False)):
            existing.liked = False
            db.add(existing)
            db.commit()
    else:
        swipe = Swipe(swiper_id=current_user.id, target_user_id=target_user_id, liked=liked)
        db.add(swipe)
        db.commit()

    bump_user_cache_version("discover_feed", int(current_user.id))
    track_event(
        db,
        "swipe_created",
        user_id=current_user.id,
        payload={
            "target_user_id": target_user_id,
            "liked": liked,
            "super_like": super_like and liked,
            "target_is_demo": target_is_demo,
        },
    )
    if not liked:
        _store_last_swipe(int(current_user.id), target_user_id=int(target_user_id), liked=False)
        return {"liked": False, "matched": False, "match_id": None, "conversation_id": None, "partner": None, "message": "Passed"}

    # Demo bot path: when a real user likes a demo profile, force reciprocal like + instant match.
    if target_is_demo and not bool(getattr(current_user, "is_demo", False)):
        reciprocal = (
            db.query(Swipe)
            .filter(Swipe.swiper_id == target_user_id, Swipe.target_user_id == current_user.id)
            .first()
        )
        if reciprocal:
            if not bool(getattr(reciprocal, "liked", False)):
                reciprocal.liked = True
                db.add(reciprocal)
                db.commit()
        else:
            db.add(Swipe(swiper_id=target_user_id, target_user_id=current_user.id, liked=True))
            db.commit()
        pair = create_match_if_mutual(db, int(current_user.id), int(target_user_id), action="demo_swipe_like")
        if not pair.get("matched"):
            _store_last_swipe(int(current_user.id), target_user_id=int(target_user_id), liked=True)
            return {
                "liked": True,
                "matched": False,
                "match_id": None,
                "conversation_id": None,
                "partner": _partner_payload(db, int(target_user_id)),
                "message": "Like sent",
            }
        match_id = int(pair["match_id"])
        a, b = sorted([int(current_user.id), int(target_user_id)])
        publish_event("match_created", {"match_id": match_id, "user_a_id": a, "user_b_id": b})
        track_event(db, "demo_chat_started", user_id=current_user.id, payload={"partner_user_id": target_user_id, "source": "demo_swipe"})
        if is_onboarding_completed:
            schedule_demo_first_message_maybe(db, target_user_id, current_user.id)
        # In dev / non-live mode, process immediate due demo messages now.
        try:
            run_demo_behavior_tick(db)
        except Exception:
            pass
        bump_user_cache_version("discover_feed", int(current_user.id))
        bump_user_cache_version("discover_feed", int(target_user_id))
        _store_last_swipe(int(current_user.id), target_user_id=int(target_user_id), liked=True)
        return {
            "liked": True,
            "matched": True,
            "match_id": match_id,
            "conversation_id": int(pair.get("conversation_id") or target_user_id),
            "partner_user_id": target_user_id,
            "partner": _partner_payload(db, int(target_user_id)),
            "chat_url": f"/chat/{int(target_user_id)}?match=1&focus=1",
            "is_demo_match": True,
            "match_title": "It's a match",
            "match_subtitle": "This demo profile will show you how NEYRA chat works.",
            "cta_open_chat": "Open chat",
            "cta_try_ai_suggestions": "Try AI reply suggestions",
            "message": "It's a match!",
        }

    # Match when reciprocal like already exists (always — no probabilistic suppression).
    reciprocal = db.query(Swipe).filter(Swipe.swiper_id == target_user_id, Swipe.target_user_id == current_user.id, Swipe.liked == True).first()
    if reciprocal:
        user_had_any_match_before = (
            int(
                db.query(func.count(Match.id))
                .filter(or_(Match.user_a_id == current_user.id, Match.user_b_id == current_user.id))
                .scalar()
                or 0
            )
            > 0
        )
        pair = create_match_if_mutual(db, int(current_user.id), int(target_user_id), action="swipe_like")
        if pair.get("matched"):
            match_id = int(pair["match_id"])
            a, b = sorted([int(current_user.id), int(target_user_id)])
            if pair.get("match_row_created") and not user_had_any_match_before:
                track_event(db, "first_match_created", user_id=current_user.id, payload={"match_id": match_id, "partner_user_id": target_user_id})
            publish_event("match_created", {"match_id": match_id, "user_a_id": a, "user_b_id": b})
            if target_is_demo:
                track_event(db, "demo_chat_started", user_id=current_user.id, payload={"partner_user_id": target_user_id, "source": "demo_swipe"})
                if is_onboarding_completed:
                    schedule_demo_first_message_maybe(db, target_user_id, current_user.id)
            bump_user_cache_version("discover_feed", int(current_user.id))
            bump_user_cache_version("discover_feed", int(target_user_id))
            _store_last_swipe(int(current_user.id), target_user_id=int(target_user_id), liked=True)
            return {
                "liked": True,
                "matched": True,
                "match_id": match_id,
                "conversation_id": int(pair.get("conversation_id") or target_user_id),
                "partner_user_id": target_user_id,
                "partner": _partner_payload(db, int(target_user_id)),
                "chat_url": f"/chat/{int(target_user_id)}?match=1&focus=1",
                "message": "It's a match!",
            }
    _store_last_swipe(int(current_user.id), target_user_id=int(target_user_id), liked=True)
    return {
        "liked": True,
        "matched": False,
        "match_id": None,
        "conversation_id": None,
        "partner": _partner_payload(db, int(target_user_id)),
        "message": "Like sent",
    }


@router.post("/undo")
def undo_last_swipe(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Undo the user's last swipe (1 free undo per UTC day).
    Best-effort: if the swipe created a Match, the Match is deleted too.
    """
    day = _utc_day_sig()
    try:
        used_ck = cache_key("swipe_undo_used", {"user_id": int(current_user.id), "day": day})
        used = cache_get(used_ck)
        if used:
            raise HTTPException(status_code=402, detail=api_error("paywall.undo_limit", max=FREE_UNDO_LIMIT_PER_DAY))
    except HTTPException:
        raise
    except Exception:
        # If cache is unavailable, fail closed (no free undo).
        raise HTTPException(status_code=503, detail=api_error("swipes.undo_unavailable"))

    ck = cache_key("last_swipe", {"user_id": int(current_user.id)})
    last = cache_get(ck)
    if not isinstance(last, dict) or not last.get("target_user_id"):
        raise HTTPException(status_code=404, detail=api_error("swipes.no_last_swipe"))
    try:
        target_user_id = int(last.get("target_user_id") or 0)
    except Exception:
        raise HTTPException(status_code=404, detail=api_error("swipes.no_last_swipe"))
    if target_user_id < 1:
        raise HTTPException(status_code=404, detail=api_error("swipes.no_last_swipe"))

    swipe = db.query(Swipe).filter(Swipe.swiper_id == int(current_user.id), Swipe.target_user_id == int(target_user_id)).first()
    if not swipe:
        raise HTTPException(status_code=404, detail=api_error("swipes.no_last_swipe"))

    # Remove match if it exists (best-effort).
    try:
        a, b = sorted([int(current_user.id), int(target_user_id)])
        match = db.query(Match).filter(Match.user_a_id == a, Match.user_b_id == b).first()
        if match:
            db.delete(match)
            db.commit()
    except Exception:
        db.rollback()
        # ignore

    try:
        db.delete(swipe)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail=api_error("swipes.undo_failed"))

    bump_user_cache_version("discover_feed", int(current_user.id))
    track_event(db, "swipe_undone", user_id=current_user.id, payload={"target_user_id": int(target_user_id)})

    try:
        cache_set(used_ck, {"ok": True}, ttl_s=36 * 60 * 60)
    except Exception:
        pass
    try:
        cache_set(ck, {}, ttl_s=5)
    except Exception:
        pass
    return {"ok": True, "target_user_id": int(target_user_id)}


@router.post("/like")
def swipe_like(payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Convenience endpoint: POST /api/v1/swipes/like with {target_user_id, super_like?}.
    """
    shaped = dict(payload or {})
    shaped["liked"] = True
    return create_swipe(shaped, current_user=current_user, db=db)


@router.post("/pass")
def swipe_pass(payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Convenience endpoint: POST /api/v1/swipes/pass with {target_user_id}.
    """
    shaped = dict(payload or {})
    shaped["liked"] = False
    return create_swipe(shaped, current_user=current_user, db=db)
